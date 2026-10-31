"""Explicit, previewed cross-project test-case copying."""

from __future__ import annotations

import shutil
import uuid
import logging
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload

from .. import models, rbac, schemas
from ..auth import get_current_active_user
from ..database import get_db
from ..crud_modules.tags import resolve_or_create_tags, sync_tags_cache
from ..import_export_modules.helpers import (
    begin_idempotent_request,
    complete_idempotent_request,
    fail_idempotent_request,
    get_idempotency_key,
)
from .test_case_images import _image_path


logger = logging.getLogger(__name__)


def _record_copy_audits(db: Session, current_user: models.User, project_id: int, copied: list[dict]) -> None:
    """Best-effort audit entries for every newly created target case."""
    try:
        from ..schemas_audit import AuditTrailCreate
        from ..services.audit_service import get_audit_service

        audit_service = get_audit_service(db)
        for row in copied:
            audit_service.create_audit_trail(AuditTrailCreate(
                user_id=current_user.id,
                action=models.AuditAction.CREATE.value,
                entity_type=models.EntityType.TEST_CASE.value,
                entity_id=row["test_case_id"],
                project_id=project_id,
                description=f"Copied test case from project case {row['source_test_case_id']}",
            ))
    except Exception:
        logger.exception("Failed to create cross-project copy audit entries")


class CrossProjectCopyRequest(BaseModel):
    test_case_ids: list[int] = Field(min_length=1, max_length=500)
    target_test_suite_id: int
    target_section_id: int | None = None


def _context(db: Session, user: models.User, payload: CrossProjectCopyRequest):
    case_ids = list(dict.fromkeys(payload.test_case_ids))
    cases = db.query(models.TestCase).options(
        selectinload(models.TestCase.test_steps),
        selectinload(models.TestCase.images),
        selectinload(models.TestCase.tags),
        selectinload(models.TestCase.custom_field_values).selectinload(models.CustomFieldValue.field_definition),
    ).filter(models.TestCase.id.in_(case_ids), models.TestCase.is_deleted.is_(False)).all()
    found = {case.id: case for case in cases}
    missing = [case_id for case_id in case_ids if case_id not in found]
    if missing:
        raise HTTPException(status_code=404, detail={"missing_test_case_ids": missing})
    source_projects = {case.project_id or case.test_suite.project_id for case in cases}
    denied = [project_id for project_id in source_projects if not rbac.has_permission(user, "read", project_id, db)]
    if denied:
        raise HTTPException(status_code=403, detail="Insufficient source project permissions")

    suite = db.query(models.TestSuite).filter(models.TestSuite.id == payload.target_test_suite_id).first()
    if suite is None:
        raise HTTPException(status_code=404, detail="Target test suite not found")
    if not rbac.has_permission(user, "write", suite.project_id, db):
        raise HTTPException(status_code=403, detail="Insufficient target project permissions")
    section = None
    if payload.target_section_id is not None:
        section = db.query(models.TestCaseSection).filter(models.TestCaseSection.id == payload.target_section_id).first()
        if section is None or section.test_suite_id != suite.id:
            raise HTTPException(status_code=400, detail="Target section does not belong to the target test suite")
    if source_projects == {suite.project_id}:
        raise HTTPException(status_code=400, detail="Use normal copy for the same project")
    return [found[case_id] for case_id in case_ids], suite, section


def _field_key(definition: models.CustomFieldDefinition) -> tuple[str, str]:
    name = (definition.slug or definition.name).strip().lower()
    field_type = getattr(definition.field_type, "value", definition.field_type)
    return name, str(field_type)


def _preview(db: Session, cases: list[models.TestCase], suite: models.TestSuite) -> dict:
    target_types = {row.name.lower() for row in db.query(models.TestTypeDefinition).filter(
        models.TestTypeDefinition.project_id == suite.project_id, models.TestTypeDefinition.is_active.is_(True),
    ).all()}
    target_priorities = {row.name.lower() for row in db.query(models.PriorityDefinition).filter(
        models.PriorityDefinition.project_id == suite.project_id, models.PriorityDefinition.is_active.is_(True),
    ).all()}
    target_fields = {_field_key(row): row for row in db.query(models.CustomFieldDefinition).filter(
        models.CustomFieldDefinition.project_id == suite.project_id,
    ).all() if not row.entity_types or "test_case" in row.entity_types}
    rows = []
    can_copy = True
    for case in cases:
        warnings: list[str] = []
        incompatible: list[str] = []
        if target_types and (case.test_type or "").lower() not in target_types:
            incompatible.append(f"test_type:{case.test_type}")
        if target_priorities and (case.priority or "").lower() not in target_priorities:
            incompatible.append(f"priority:{case.priority}")
        source_values = {_field_key(value.field_definition): value for value in case.custom_field_values if value.field_definition}
        unmapped = [value.field_definition.name for key, value in source_values.items() if key not in target_fields]
        if unmapped:
            warnings.append("Unmapped custom fields: " + ", ".join(sorted(unmapped)))
        missing_required = [definition.name for key, definition in target_fields.items() if definition.is_required and key not in source_values]
        if missing_required:
            incompatible.append("required custom fields:" + ", ".join(sorted(missing_required)))
        missing_images = [image.filename for image in case.images if not _image_path(case, image.storage_key).is_file()]
        if missing_images:
            incompatible.append("missing attachments:" + ", ".join(missing_images))
        if incompatible:
            can_copy = False
        rows.append({
            "test_case_id": case.id, "title": case.title, "step_count": len(case.test_steps),
            "image_count": len(case.images), "warnings": warnings, "incompatible": incompatible,
        })
    return {"can_copy": can_copy, "target_project_id": suite.project_id, "target_test_suite_id": suite.id, "cases": rows}


def register_test_case_cross_project_copy_routes(app) -> None:
    @app.post("/test-cases/cross-project-copy/preview")
    def preview_cross_project_copy(
        payload: CrossProjectCopyRequest,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        cases, suite, _section = _context(db, current_user, payload)
        return _preview(db, cases, suite)

    @app.post("/test-cases/cross-project-copy/commit")
    def commit_cross_project_copy(
        payload: CrossProjectCopyRequest,
        request: Request,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        record_key = get_idempotency_key(request, current_user.id, "cross-project-case-copy")
        if record_key is None:
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        cached = begin_idempotent_request(db, record_key, current_user.id, "cross-project-case-copy")
        if cached is not None:
            return cached
        created_paths: list[Path] = []
        try:
            cases, suite, section = _context(db, current_user, payload)
            preview = _preview(db, cases, suite)
            if not preview["can_copy"]:
                raise HTTPException(status_code=400, detail=preview)
            target_fields = {_field_key(row): row for row in db.query(models.CustomFieldDefinition).filter(
                models.CustomFieldDefinition.project_id == suite.project_id,
            ).all() if not row.entity_types or "test_case" in row.entity_types}
            copied = []
            for source in cases:
                target = models.TestCase(
                    title=source.title, description=source.description, test_type=source.test_type,
                    preconditions=source.preconditions, steps=source.steps, expected_result=source.expected_result,
                    priority=source.priority, status=source.status, reference=source.reference,
                    test_suite_id=suite.id, section_id=section.id if section else None,
                    project_id=suite.project_id, order_index=source.order_index, is_multistep=source.is_multistep,
                    created_by=current_user.id,
                )
                target.tags = resolve_or_create_tags(db, suite.project_id, [tag.name for tag in source.tags], current_user.id)
                sync_tags_cache(target)
                db.add(target)
                db.flush()
                step_map = {}
                for step in sorted(source.test_steps, key=lambda item: (item.order_index, item.step_number)):
                    copied_step = models.TestCaseStep(
                        test_case_id=target.id, step_number=step.step_number, action=step.action,
                        expected_result=step.expected_result, step_type=step.step_type, data=step.data,
                        order_index=step.order_index,
                    )
                    db.add(copied_step)
                    db.flush()
                    step_map[step.id] = copied_step.id
                for value in source.custom_field_values:
                    definition = target_fields.get(_field_key(value.field_definition)) if value.field_definition else None
                    if definition:
                        db.add(models.CustomFieldValue(field_definition_id=definition.id, test_case_id=target.id, value=value.value))
                for image in source.images:
                    suffix = Path(image.storage_key).suffix
                    storage_key = f"{uuid.uuid4().hex}{suffix}"
                    copied_image = models.TestCaseImage(
                        test_case_id=target.id, test_step_id=step_map.get(image.test_step_id), filename=image.filename,
                        storage_key=storage_key, mime_type=image.mime_type, file_size=image.file_size,
                        sha256=image.sha256, alt_text=image.alt_text, uploaded_by=current_user.id,
                    )
                    destination = _image_path(target, storage_key)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(_image_path(source, image.storage_key), destination)
                    created_paths.append(destination)
                    db.add(copied_image)
                copied.append({"source_test_case_id": source.id, "test_case_id": target.id, "project_seq": target.project_seq, "title": target.title})
            db.commit()
            response = {"copied_count": len(copied), "target_project_id": suite.project_id, "target_test_suite_id": suite.id, "cases": copied}
            _record_copy_audits(db, current_user, suite.project_id, copied)
            complete_idempotent_request(db, record_key, response)
            return response
        except HTTPException as error:
            db.rollback()
            for path in created_paths:
                path.unlink(missing_ok=True)
            fail_idempotent_request(db, record_key, str(error.detail))
            raise
        except Exception as error:
            db.rollback()
            for path in created_paths:
                path.unlink(missing_ok=True)
            fail_idempotent_request(db, record_key, str(error))
            raise
