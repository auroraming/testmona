"""Versioned review tasks for test cases and mind-map module selections."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload

from .. import models, rbac, schemas
from ..auth import get_current_active_user
from ..database import get_db
from ..services import notification_engine
from ..services.test_case_review_service import snapshot_test_case


class ReviewTaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    test_suite_id: int
    test_case_ids: list[int] = Field(min_length=1, max_length=500)
    reviewer_ids: list[int] = Field(min_length=1, max_length=20)
    mode: Literal["single", "multiple"] = "single"
    due_at: datetime | None = None


class ReviewDecision(BaseModel):
    decision: Literal["approved", "changes_requested"]
    comment: str | None = Field(default=None, max_length=2000)
    has_suggestion: bool = False


class ReviewerUpdate(BaseModel):
    reviewer_ids: list[int] = Field(min_length=1, max_length=20)


class RereviewCreate(BaseModel):
    test_case_ids: list[int] | None = Field(default=None, max_length=500)


def _task_query(db: Session):
    return db.query(models.TestCaseReviewTask).options(
        selectinload(models.TestCaseReviewTask.rounds).selectinload(models.TestCaseReviewRound.assignments),
        selectinload(models.TestCaseReviewTask.rounds).selectinload(models.TestCaseReviewRound.test_case),
    )


def _reviewers(db: Session, reviewer_ids: list[int], project_id: int) -> list[models.User]:
    ids = list(dict.fromkeys(reviewer_ids))
    users = db.query(models.User).filter(models.User.id.in_(ids), models.User.is_active.is_(True)).all()
    found = {user.id: user for user in users}
    missing = [reviewer_id for reviewer_id in ids if reviewer_id not in found]
    if missing:
        raise HTTPException(status_code=400, detail={"invalid_reviewer_ids": missing})
    denied = [reviewer_id for reviewer_id in ids if not rbac.has_permission(found[reviewer_id], "read", project_id, db)]
    if denied:
        raise HTTPException(status_code=400, detail={"reviewers_without_project_access": denied})
    return [found[reviewer_id] for reviewer_id in ids]


def _snapshot(db: Session, test_case: models.TestCase) -> tuple[int, dict]:
    return snapshot_test_case(db, test_case)


def _recompute(task: models.TestCaseReviewTask) -> None:
    current = {}
    for round_ in task.rounds:
        previous = current.get(round_.test_case_id)
        if previous is None or round_.round_number > previous.round_number:
            current[round_.test_case_id] = round_
    statuses = [round_.status for round_ in current.values()]
    if any(status == "changes_requested" for status in statuses):
        task.status = "changes_requested"
    elif statuses and all(status == "approved" for status in statuses):
        task.status = "approved"
    else:
        task.status = "pending"


def _recompute_round(round_: models.TestCaseReviewRound) -> None:
    active = [assignment for assignment in round_.assignments if assignment.is_active]
    decisions = [assignment.decision for assignment in active]
    if any(decision == "changes_requested" for decision in decisions):
        round_.status = "changes_requested"
    elif decisions and all(decision == "approved" for decision in decisions):
        round_.status = "approved"
    else:
        round_.status = "pending"
    round_.resolved_at = datetime.now(timezone.utc) if round_.status != "pending" else None


def _view(task: models.TestCaseReviewTask) -> dict:
    rounds = []
    for round_ in task.rounds:
        rounds.append({
            "id": round_.id, "test_case_id": round_.test_case_id,
            "test_case_title": round_.snapshot.get("title") or (round_.test_case.title if round_.test_case else ""),
            "round_number": round_.round_number, "revision_number": round_.revision_number,
            "snapshot": round_.snapshot, "status": round_.status, "submitted_by": round_.submitted_by,
            "created_at": round_.created_at, "resolved_at": round_.resolved_at,
            "assignments": [
                {"id": item.id, "reviewer_id": item.reviewer_id, "is_active": item.is_active,
                 "decision": item.decision, "comment": item.comment, "has_suggestion": item.has_suggestion,
                 "decided_at": item.decided_at, "removed_at": item.removed_at}
                for item in round_.assignments
            ],
        })
    return {
        "id": task.id, "project_id": task.project_id, "test_suite_id": task.test_suite_id,
        "name": task.name, "mode": task.mode, "status": task.status,
        "requested_by": task.requested_by, "due_at": task.due_at,
        "created_at": task.created_at, "updated_at": task.updated_at, "rounds": rounds,
    }


def _get_task(db: Session, task_id: int, user: models.User, permission: str = "read") -> models.TestCaseReviewTask:
    task = _task_query(db).filter(models.TestCaseReviewTask.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Review task not found")
    if not rbac.has_permission(user, permission, task.project_id, db):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return task


def _audit(db: Session, user: models.User, task: models.TestCaseReviewTask, action: models.AuditAction,
           description: str, **metadata) -> None:
    """Best-effort audit through the existing project audit service."""
    try:
        from ..schemas_audit import AuditTrailCreate
        from ..services.audit_service import get_audit_service

        get_audit_service(db).create_audit_trail(AuditTrailCreate(
            user_id=user.id,
            action=action,
            entity_type=models.EntityType.TEST_SUITE,
            entity_id=task.test_suite_id,
            project_id=task.project_id,
            description=description,
            additional_metadata={"review_task_id": task.id, **metadata},
        ))
    except Exception:
        # Auditing is configurable and best-effort throughout the application;
        # an unavailable audit sink must not undo a completed review action.
        db.rollback()


def _notify_reviewers(db: Session, task: models.TestCaseReviewTask, reviewer_ids: list[int],
                      actor: models.User, *, title: str, message: str) -> None:
    notification_engine.emit(
        db,
        category=notification_engine.REVIEW,
        user_ids=reviewer_ids,
        actor_id=actor.id,
        title=title,
        message=message,
        related_entity_type="test_case_review_task",
        related_entity_id=task.id,
    )


def register_test_case_review_routes(app) -> None:
    @app.post("/test-case-review-tasks", status_code=201)
    def create_review_task(payload: ReviewTaskCreate, db: Session = Depends(get_db),
                           current_user: schemas.User = Depends(get_current_active_user)):
        suite = db.query(models.TestSuite).filter(models.TestSuite.id == payload.test_suite_id).first()
        if suite is None:
            raise HTTPException(status_code=404, detail="Test suite not found")
        if not rbac.has_permission(current_user, "write", suite.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        reviewer_ids = list(dict.fromkeys(payload.reviewer_ids))
        if payload.mode == "single" and len(reviewer_ids) != 1:
            raise HTTPException(status_code=400, detail="Single-reviewer mode requires exactly one reviewer")
        _reviewers(db, reviewer_ids, suite.project_id)
        case_ids = list(dict.fromkeys(payload.test_case_ids))
        cases = db.query(models.TestCase).filter(
            models.TestCase.id.in_(case_ids), models.TestCase.test_suite_id == suite.id,
            models.TestCase.is_deleted.is_(False),
        ).all()
        found = {case.id for case in cases}
        missing = [case_id for case_id in case_ids if case_id not in found]
        if missing:
            raise HTTPException(status_code=400, detail={"invalid_test_case_ids": missing})
        task = models.TestCaseReviewTask(
            project_id=suite.project_id, test_suite_id=suite.id, name=payload.name.strip(),
            mode=payload.mode, requested_by=current_user.id, due_at=payload.due_at,
        )
        db.add(task)
        db.flush()
        by_id = {case.id: case for case in cases}
        for case_id in case_ids:
            revision, snapshot = _snapshot(db, by_id[case_id])
            round_ = models.TestCaseReviewRound(
                task=task, test_case_id=case_id, round_number=1,
                revision_number=revision, snapshot=snapshot, submitted_by=current_user.id,
            )
            db.add(round_)
            db.flush()
            for reviewer_id in reviewer_ids:
                db.add(models.TestCaseReviewAssignment(round_id=round_.id, reviewer_id=reviewer_id))
        db.commit()
        task = _get_task(db, task.id, current_user)
        _notify_reviewers(
            db, task, reviewer_ids, current_user,
            title="Test case review requested",
            message=f'{notification_engine.actor_display_name(current_user)} requested your review of "{task.name}".',
        )
        _audit(
            db, current_user, task, models.AuditAction.CREATE,
            f"Test case review task created: {task.name}",
            test_case_ids=case_ids, reviewer_ids=reviewer_ids, mode=task.mode,
        )
        return _view(_get_task(db, task.id, current_user))

    @app.get("/test-case-review-tasks")
    def list_review_tasks(project_id: int = Query(..., ge=1), db: Session = Depends(get_db),
                          current_user: schemas.User = Depends(get_current_active_user)):
        if not rbac.has_permission(current_user, "read", project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        tasks = _task_query(db).filter(models.TestCaseReviewTask.project_id == project_id).order_by(
            models.TestCaseReviewTask.id.desc(),
        ).all()
        return [_view(task) for task in tasks]

    @app.get("/test-case-review-tasks/{task_id}")
    def get_review_task(task_id: int, db: Session = Depends(get_db),
                        current_user: schemas.User = Depends(get_current_active_user)):
        return _view(_get_task(db, task_id, current_user))

    @app.post("/test-case-review-rounds/{round_id}/decision")
    def decide_review(round_id: int, payload: ReviewDecision, db: Session = Depends(get_db),
                      current_user: schemas.User = Depends(get_current_active_user)):
        round_ = db.query(models.TestCaseReviewRound).options(
            selectinload(models.TestCaseReviewRound.assignments),
            selectinload(models.TestCaseReviewRound.task).selectinload(models.TestCaseReviewTask.rounds).selectinload(
                models.TestCaseReviewRound.assignments),
        ).filter(models.TestCaseReviewRound.id == round_id).first()
        if round_ is None:
            raise HTTPException(status_code=404, detail="Review round not found")
        assignment = next((item for item in round_.assignments if item.reviewer_id == current_user.id and item.is_active), None)
        if assignment is None:
            raise HTTPException(status_code=403, detail="Only an active reviewer may decide this round")
        assignment.decision = payload.decision
        assignment.comment = payload.comment.strip() if payload.comment else None
        assignment.has_suggestion = payload.has_suggestion
        assignment.decided_at = datetime.now(timezone.utc)
        _recompute_round(round_)
        _recompute(round_.task)
        if round_.status == "approved":
            test_case = db.query(models.TestCase).filter(models.TestCase.id == round_.test_case_id).first()
            if test_case is not None:
                _revision, current_snapshot = _snapshot(db, test_case)
                if current_snapshot == round_.snapshot:
                    test_case.review_required = False
                    test_case.review_required_at = None
                    test_case.review_required_reason = None
        db.commit()
        task = _get_task(db, round_.task_id, current_user)
        notification_engine.emit(
            db,
            category=notification_engine.REVIEW,
            user_ids=[task.requested_by],
            actor_id=current_user.id,
            title="Test case review updated",
            message=(
                f'{notification_engine.actor_display_name(current_user)} approved "{round_.snapshot.get("title", "Test case")}".'
                if payload.decision == "approved"
                else f'{notification_engine.actor_display_name(current_user)} requested changes on "{round_.snapshot.get("title", "Test case")}".'
            ),
            related_entity_type="test_case_review_task",
            related_entity_id=task.id,
            type_override=(notification_engine.NotificationType.SUCCESS if payload.decision == "approved" else notification_engine.NotificationType.WARNING),
        )
        _audit(
            db, current_user, task,
            models.AuditAction.APPROVE if payload.decision == "approved" else models.AuditAction.REJECT,
            f"Test case review decision: {payload.decision}",
            round_id=round_.id, test_case_id=round_.test_case_id,
            has_suggestion=payload.has_suggestion,
        )
        return _view(_get_task(db, round_.task_id, current_user))

    @app.put("/test-case-review-rounds/{round_id}/reviewers")
    def update_reviewers(round_id: int, payload: ReviewerUpdate, db: Session = Depends(get_db),
                         current_user: schemas.User = Depends(get_current_active_user)):
        round_ = db.query(models.TestCaseReviewRound).options(
            selectinload(models.TestCaseReviewRound.assignments), selectinload(models.TestCaseReviewRound.task),
        ).filter(models.TestCaseReviewRound.id == round_id).first()
        if round_ is None:
            raise HTTPException(status_code=404, detail="Review round not found")
        if not rbac.has_permission(current_user, "write", round_.task.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        reviewer_ids = list(dict.fromkeys(payload.reviewer_ids))
        if round_.task.mode == "single" and len(reviewer_ids) != 1:
            raise HTTPException(status_code=400, detail="Single-reviewer mode requires exactly one reviewer")
        _reviewers(db, reviewer_ids, round_.task.project_id)
        now = datetime.now(timezone.utc)
        existing = {item.reviewer_id: item for item in round_.assignments}
        added_ids = [reviewer_id for reviewer_id in reviewer_ids if reviewer_id not in existing or not existing[reviewer_id].is_active]
        for item in round_.assignments:
            if item.reviewer_id not in reviewer_ids and item.is_active:
                item.is_active = False
                item.removed_at = now
        for reviewer_id in reviewer_ids:
            item = existing.get(reviewer_id)
            if item:
                item.is_active = True
                item.removed_at = None
            else:
                db.add(models.TestCaseReviewAssignment(round_id=round_.id, reviewer_id=reviewer_id))
        db.flush()
        db.refresh(round_)
        _recompute_round(round_)
        _recompute(round_.task)
        db.commit()
        task = _get_task(db, round_.task_id, current_user)
        if added_ids:
            _notify_reviewers(
                db, task, added_ids, current_user,
                title="Test case review assigned",
                message=f'{notification_engine.actor_display_name(current_user)} assigned you to "{task.name}".',
            )
        _audit(
            db, current_user, task, models.AuditAction.ASSIGN,
            f"Test case review reviewers updated: {task.name}",
            round_id=round_.id, reviewer_ids=reviewer_ids,
        )
        return _view(_get_task(db, round_.task_id, current_user))

    @app.post("/test-case-review-tasks/{task_id}/rereview", status_code=201)
    def rereview(task_id: int, payload: RereviewCreate, db: Session = Depends(get_db),
                 current_user: schemas.User = Depends(get_current_active_user)):
        task = _get_task(db, task_id, current_user, "write")
        current = {}
        for round_ in task.rounds:
            if round_.test_case_id not in current or round_.round_number > current[round_.test_case_id].round_number:
                current[round_.test_case_id] = round_
        selected = list(dict.fromkeys(payload.test_case_ids or list(current)))
        if not selected or any(case_id not in current for case_id in selected):
            raise HTTPException(status_code=400, detail="Re-review cases must already belong to the task")
        for case_id in selected:
            previous = current[case_id]
            if previous.status == "pending":
                raise HTTPException(status_code=409, detail=f"Test case {case_id} still has a pending review round")
            test_case = db.query(models.TestCase).filter(
                models.TestCase.id == case_id, models.TestCase.is_deleted.is_(False),
            ).first()
            if test_case is None:
                raise HTTPException(status_code=409, detail=f"Test case {case_id} is unavailable")
            reviewer_ids = [item.reviewer_id for item in previous.assignments if item.is_active]
            revision, snapshot = _snapshot(db, test_case)
            round_ = models.TestCaseReviewRound(
                task=task, test_case_id=case_id, round_number=previous.round_number + 1,
                revision_number=revision, snapshot=snapshot, submitted_by=current_user.id,
            )
            db.add(round_)
            db.flush()
            for reviewer_id in reviewer_ids:
                db.add(models.TestCaseReviewAssignment(round_id=round_.id, reviewer_id=reviewer_id))
        db.flush()
        _recompute(task)
        db.commit()
        task = _get_task(db, task.id, current_user)
        rereview_reviewer_ids = sorted({
            assignment.reviewer_id
            for round_ in task.rounds
            if round_.test_case_id in selected and round_.round_number == current[round_.test_case_id].round_number + 1
            for assignment in round_.assignments if assignment.is_active
        })
        _notify_reviewers(
            db, task, rereview_reviewer_ids, current_user,
            title="Test case re-review requested",
            message=f'{notification_engine.actor_display_name(current_user)} opened a new round for "{task.name}".',
        )
        _audit(
            db, current_user, task, models.AuditAction.UPDATE,
            f"Test case review task resubmitted: {task.name}", test_case_ids=selected,
        )
        return _view(_get_task(db, task.id, current_user))
