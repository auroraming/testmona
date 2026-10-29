from fastapi import Depends, File, Form, HTTPException, Path, Query, UploadFile
from sqlalchemy.orm import Session, joinedload, selectinload
from typing import List, Optional
from sqlalchemy import desc, case, func, cast, Date
from datetime import datetime, timedelta, timezone
import logging
import re

from .. import crud, schemas, auth, rbac, models
from ..feature_guard import require_project_feature
from ..database import get_db
from ..auth import get_current_active_user, get_current_user
from ..models import TestCase, TestResult, TestRun, User, TestCaseRevision, ResultStatus, canonical_result_status
from .test_management_helpers import *

logger = logging.getLogger(__name__)


def _mindmap_nodes(mindmap_data: Optional[dict]) -> dict[str, dict]:
    if not isinstance(mindmap_data, dict):
        return {}
    nodes = mindmap_data.get("nodes")
    if not isinstance(nodes, list):
        return {}
    return {
        str(node.get("id")): node
        for node in nodes
        if isinstance(node, dict) and node.get("id") is not None
    }


def register_analysis_routes(app):
    @app.post("/test-mindmaps/", response_model=schemas.TestMindmap)
    def create_test_mindmap(
        mindmap: schemas.TestMindmapCreate,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user)
    ):
        if not rbac.has_permission(current_user, "write", mindmap.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        payload = mindmap.model_dump()
        payload["created_by"] = current_user.id
        return crud.create_test_mindmap(db=db, mindmap=payload)

    @app.get("/test-mindmaps/", response_model=List[schemas.TestMindmap])
    def read_test_mindmaps(
        project_id: int = None,
        skip: int = 0,
        limit: int = 100,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user)
    ):
        if project_id is not None:
            if not rbac.has_permission(current_user, "read", project_id, db):
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return crud.get_test_mindmaps(db, project_id=project_id, skip=skip, limit=limit)

        accessible_ids = [project.id for project in rbac.get_accessible_projects(current_user, db)]
        if not accessible_ids:
            return []
        return (
            db.query(models.TestMindmap)
            .filter(
                models.TestMindmap.is_active == True,  # noqa: E712
                models.TestMindmap.project_id.in_(accessible_ids),
            )
            .order_by(models.TestMindmap.name)
            .offset(skip)
            .limit(limit)
            .all()
        )

    @app.get("/test-mindmaps/{mindmap_id}", response_model=schemas.TestMindmap)
    def read_test_mindmap(
        mindmap_id: int,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user)
    ):
        mindmap = crud.get_test_mindmap(db, mindmap_id=mindmap_id)
        if mindmap is None:
            raise HTTPException(status_code=404, detail="Test mindmap not found")
        
        if not rbac.has_permission(current_user, "read", mindmap.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        return mindmap

    @app.put("/test-mindmaps/{mindmap_id}", response_model=schemas.TestMindmap)
    def update_test_mindmap(
        mindmap_id: int,
        mindmap: schemas.TestMindmapUpdate,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user)
    ):
        db_mindmap = crud.get_test_mindmap(db, mindmap_id=mindmap_id)
        if db_mindmap is None:
            raise HTTPException(status_code=404, detail="Test mindmap not found")
        
        if not rbac.has_permission(current_user, "write", db_mindmap.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        update_fields = mindmap.model_dump(exclude_unset=True)
        updated = crud.update_test_mindmap(db, mindmap_id=mindmap_id, mindmap=update_fields)
        if "mindmap_data" in update_fields:
            valid_node_ids = set(_mindmap_nodes(update_fields["mindmap_data"]))
            link_query = db.query(models.TestMindmapTestCaseLink).filter(
                models.TestMindmapTestCaseLink.mindmap_id == mindmap_id
            )
            if valid_node_ids:
                link_query.filter(
                    ~models.TestMindmapTestCaseLink.node_id.in_(valid_node_ids)
                ).delete(synchronize_session=False)
            else:
                link_query.delete(synchronize_session=False)
            db.commit()
        return updated

    @app.delete("/test-mindmaps/{mindmap_id}", response_model=schemas.MessageResponse)
    def delete_test_mindmap(
        mindmap_id: int,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user)
    ):
        db_mindmap = crud.get_test_mindmap(db, mindmap_id=mindmap_id)
        if db_mindmap is None:
            raise HTTPException(status_code=404, detail="Test mindmap not found")
        
        if not rbac.has_permission(current_user, "delete", db_mindmap.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        crud.delete_test_mindmap(db, mindmap_id=mindmap_id)
        return {"message": "Test mindmap deleted successfully"}

    @app.get(
        "/test-mindmaps/{mindmap_id}/nodes/{node_id}/test-cases",
        response_model=List[schemas.TestMindmapLinkedTestCase],
    )
    def read_mindmap_node_test_cases(
        mindmap_id: int,
        node_id: str,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        mindmap = crud.get_test_mindmap(db, mindmap_id=mindmap_id)
        if mindmap is None:
            raise HTTPException(status_code=404, detail="Test mindmap not found")
        if not rbac.has_permission(current_user, "read", mindmap.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        if node_id not in _mindmap_nodes(mindmap.mindmap_data):
            raise HTTPException(status_code=404, detail="Mindmap node not found")

        rows = (
            db.query(models.TestMindmapTestCaseLink, models.TestCase)
            .join(models.TestCase, models.TestCase.id == models.TestMindmapTestCaseLink.test_case_id)
            .filter(
                models.TestMindmapTestCaseLink.mindmap_id == mindmap_id,
                models.TestMindmapTestCaseLink.node_id == node_id,
                ((models.TestCase.is_deleted.is_(None)) | (models.TestCase.is_deleted.is_(False))),
            )
            .order_by(models.TestCase.title)
            .all()
        )
        return [
            schemas.TestMindmapLinkedTestCase(
                id=test_case.id,
                project_seq=test_case.project_seq,
                title=test_case.title,
                priority=test_case.priority,
                status=test_case.status,
                test_suite_id=test_case.test_suite_id,
                section_id=test_case.section_id,
                node_id=link.node_id,
            )
            for link, test_case in rows
        ]

    @app.get("/test-mindmaps/{mindmap_id}/links-summary")
    def read_mindmap_links_summary(
        mindmap_id: int,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        """Return per-node link counts in one query for canvas badges."""
        mindmap = crud.get_test_mindmap(db, mindmap_id=mindmap_id)
        if mindmap is None:
            raise HTTPException(status_code=404, detail="Test mindmap not found")
        if not rbac.has_permission(current_user, "read", mindmap.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        valid_node_ids = set(_mindmap_nodes(mindmap.mindmap_data))
        rows = (
            db.query(
                models.TestMindmapTestCaseLink.node_id,
                func.count(models.TestMindmapTestCaseLink.id),
            )
            .join(
                models.TestCase,
                models.TestCase.id == models.TestMindmapTestCaseLink.test_case_id,
            )
            .filter(
                models.TestMindmapTestCaseLink.mindmap_id == mindmap_id,
                ((models.TestCase.is_deleted.is_(None)) | (models.TestCase.is_deleted.is_(False))),
            )
            .group_by(models.TestMindmapTestCaseLink.node_id)
            .all()
        )
        return {
            node_id: int(count)
            for node_id, count in rows
            if node_id in valid_node_ids
        }

    @app.post(
        "/test-mindmaps/{mindmap_id}/nodes/{node_id}/test-cases",
        response_model=List[schemas.TestMindmapLinkedTestCase],
    )
    def link_mindmap_node_test_cases(
        payload: schemas.TestMindmapLinkCreate,
        mindmap_id: int,
        node_id: str,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        mindmap = crud.get_test_mindmap(db, mindmap_id=mindmap_id)
        if mindmap is None:
            raise HTTPException(status_code=404, detail="Test mindmap not found")
        if not rbac.has_permission(current_user, "write", mindmap.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        if node_id not in _mindmap_nodes(mindmap.mindmap_data):
            raise HTTPException(status_code=404, detail="Mindmap node not found")

        case_ids = list(dict.fromkeys(payload.test_case_ids))
        test_cases = (
            db.query(models.TestCase)
            .filter(
                models.TestCase.id.in_(case_ids),
                models.TestCase.project_id == mindmap.project_id,
                ((models.TestCase.is_deleted.is_(None)) | (models.TestCase.is_deleted.is_(False))),
            )
            .all()
        )
        found_ids = {test_case.id for test_case in test_cases}
        if found_ids != set(case_ids):
            raise HTTPException(
                status_code=400,
                detail="Every test case must exist and belong to the mindmap project",
            )

        existing_ids = {
            row.test_case_id
            for row in db.query(models.TestMindmapTestCaseLink).filter(
                models.TestMindmapTestCaseLink.mindmap_id == mindmap_id,
                models.TestMindmapTestCaseLink.node_id == node_id,
                models.TestMindmapTestCaseLink.test_case_id.in_(case_ids),
            )
        }
        for test_case_id in case_ids:
            if test_case_id not in existing_ids:
                db.add(models.TestMindmapTestCaseLink(
                    mindmap_id=mindmap_id,
                    node_id=node_id,
                    test_case_id=test_case_id,
                    created_by=current_user.id,
                ))
        db.commit()
        return read_mindmap_node_test_cases(mindmap_id, node_id, db, current_user)

    @app.delete(
        "/test-mindmaps/{mindmap_id}/nodes/{node_id}/test-cases/{test_case_id}",
        response_model=schemas.MessageResponse,
    )
    def unlink_mindmap_node_test_case(
        mindmap_id: int,
        node_id: str,
        test_case_id: int,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        mindmap = crud.get_test_mindmap(db, mindmap_id=mindmap_id)
        if mindmap is None:
            raise HTTPException(status_code=404, detail="Test mindmap not found")
        if not rbac.has_permission(current_user, "write", mindmap.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        link = db.query(models.TestMindmapTestCaseLink).filter(
            models.TestMindmapTestCaseLink.mindmap_id == mindmap_id,
            models.TestMindmapTestCaseLink.node_id == node_id,
            models.TestMindmapTestCaseLink.test_case_id == test_case_id,
        ).first()
        if link is None:
            raise HTTPException(status_code=404, detail="Mindmap test-case link not found")
        db.delete(link)
        db.commit()
        return {"message": "Test case unlinked from mindmap node"}

    @app.get(
        "/test-cases/{test_case_id}/mindmaps",
        response_model=List[schemas.TestCaseMindmapLink],
    )
    def read_test_case_mindmaps(
        test_case_id: int,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        test_case = db.query(models.TestCase).filter(
            models.TestCase.id == test_case_id,
            ((models.TestCase.is_deleted.is_(None)) | (models.TestCase.is_deleted.is_(False))),
        ).first()
        if test_case is None:
            raise HTTPException(status_code=404, detail="Test case not found")
        if not rbac.has_permission(current_user, "read", test_case.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        rows = (
            db.query(models.TestMindmapTestCaseLink, models.TestMindmap)
            .join(models.TestMindmap, models.TestMindmap.id == models.TestMindmapTestCaseLink.mindmap_id)
            .filter(
                models.TestMindmapTestCaseLink.test_case_id == test_case_id,
                models.TestMindmap.is_active == True,  # noqa: E712
            )
            .order_by(models.TestMindmap.name)
            .all()
        )
        result = []
        for link, mindmap in rows:
            node = _mindmap_nodes(mindmap.mindmap_data).get(link.node_id, {})
            result.append(schemas.TestCaseMindmapLink(
                mindmap_id=mindmap.id,
                mindmap_name=mindmap.name,
                node_id=link.node_id,
                node_title=node.get("title") or node.get("text") or node.get("label"),
            ))
        return result

    @app.post("/impact-analyses/", response_model=schemas.ImpactAnalysis)
    def create_impact_analysis(
        analysis: schemas.ImpactAnalysisCreate,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user)
    ):
        if not rbac.has_permission(current_user, "write", analysis.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        return crud.create_impact_analysis(db=db, analysis=analysis.model_dump())

    @app.get("/impact-analyses/", response_model=List[schemas.ImpactAnalysis])
    def read_impact_analyses(
        project_id: int = None,
        skip: int = 0,
        limit: int = 100,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user)
    ):
        if not rbac.has_permission(current_user, "read"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        return crud.get_impact_analyses(db, project_id=project_id, skip=skip, limit=limit)

    @app.get("/impact-analyses/{analysis_id}", response_model=schemas.ImpactAnalysis)
    def read_impact_analysis(
        analysis_id: int,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user)
    ):
        analysis = crud.get_impact_analysis(db, analysis_id=analysis_id)
        if analysis is None:
            raise HTTPException(status_code=404, detail="Impact analysis not found")
        
        if not rbac.has_permission(current_user, "read", analysis.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        return analysis

    @app.put("/impact-analyses/{analysis_id}", response_model=schemas.ImpactAnalysis)
    def update_impact_analysis(
        analysis_id: int,
        analysis: schemas.ImpactAnalysisUpdate,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user)
    ):
        db_analysis = crud.get_impact_analysis(db, analysis_id=analysis_id)
        if db_analysis is None:
            raise HTTPException(status_code=404, detail="Impact analysis not found")
        
        if not rbac.has_permission(current_user, "write", db_analysis.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        return crud.update_impact_analysis(db, analysis_id=analysis_id, analysis=analysis.model_dump(exclude_unset=True))

    @app.delete("/impact-analyses/{analysis_id}", response_model=schemas.MessageResponse)
    def delete_impact_analysis(
        analysis_id: int,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user)
    ):
        db_analysis = crud.get_impact_analysis(db, analysis_id=analysis_id)
        if db_analysis is None:
            raise HTTPException(status_code=404, detail="Impact analysis not found")
        
        if not rbac.has_permission(current_user, "delete", db_analysis.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        crud.delete_impact_analysis(db, analysis_id=analysis_id)
        return {"message": "Impact analysis deleted successfully"}

    @app.post("/impact-analyses/generate")
    def generate_impact_analysis(
        test_case_id: int,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user)
    ):
        test_case = crud.get_test_case(db, test_case_id=test_case_id)
        if not test_case:
            raise HTTPException(status_code=404, detail="Test case not found")
        
        test_suite = crud.get_test_suite(db, test_suite_id=test_case.test_suite_id)
        if not rbac.has_permission(current_user, "read", test_suite.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Generate impact analysis (simplified version)
        analysis = crud.create_impact_analysis(db, analysis={
            "title": f"Impact Analysis for Test Case {test_case_id}",
            "project_id": test_suite.project_id,
            "created_by": current_user.id,
            "affected_test_cases": [test_case_id]
        })
        return analysis
