"""Unified orchestration records for built-in Web, Mobile, and API automation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from fastapi import Depends, Header, HTTPException, Path, Query, Response
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, rbac, schemas
from ..auth import get_current_active_user
from ..database import get_db


TERMINAL_STATUSES = {"cancelled", "passed", "failed", "blocked", "timed_out"}
LEASE_SECONDS = 90


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _authenticate_runner(db: Session, token: str | None) -> models.AIAutomationRunner:
    if not token:
        raise HTTPException(status_code=401, detail="Runner token is required")
    runner = db.query(models.AIAutomationRunner).filter(
        models.AIAutomationRunner.token_hash == _token_hash(token)
    ).first()
    if runner is None or runner.status == "disabled":
        raise HTTPException(status_code=401, detail="Invalid runner token")
    return runner


def _verify_lease(task: models.AIAutomationTask, runner: models.AIAutomationRunner, lease_token: str) -> None:
    if task.runner_id != runner.id or not task.lease_token_hash:
        raise HTTPException(status_code=409, detail="Task is not leased to this runner")
    if not secrets.compare_digest(task.lease_token_hash, _token_hash(lease_token)):
        raise HTTPException(status_code=401, detail="Invalid task lease")


def _validate_project_links(db: Session, payload: schemas.AIAutomationTaskCreate) -> None:
    if payload.test_case_id is not None:
        test_case = db.query(models.TestCase).filter(models.TestCase.id == payload.test_case_id).first()
        if test_case is None or test_case.project_id != payload.project_id or test_case.is_deleted:
            raise HTTPException(status_code=400, detail="Test case must belong to the selected project")
    if payload.test_run_id is not None:
        test_run = db.query(models.TestRun).filter(models.TestRun.id == payload.test_run_id).first()
        if test_run is None or test_run.project_id != payload.project_id:
            raise HTTPException(status_code=400, detail="Test run must belong to the selected project")
    if payload.environment_id is not None:
        environment = db.query(models.ExecutionEnvironment).filter(
            models.ExecutionEnvironment.id == payload.environment_id
        ).first()
        if environment is None or environment.project_id != payload.project_id:
            raise HTTPException(status_code=400, detail="Environment must belong to the selected project")


def _get_task(db: Session, task_id: int) -> models.AIAutomationTask:
    task = db.query(models.AIAutomationTask).filter(models.AIAutomationTask.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="AI automation task not found")
    return task


def _get_runner(db: Session, runner_id: int) -> models.AIAutomationRunner:
    runner = db.query(models.AIAutomationRunner).filter(models.AIAutomationRunner.id == runner_id).first()
    if runner is None:
        raise HTTPException(status_code=404, detail="AI automation runner not found")
    return runner


def register_ai_automation_routes(app) -> None:
    @app.post("/ai-automation/runners", response_model=schemas.AIAutomationRunnerCreated, status_code=201)
    def register_ai_automation_runner(
        payload: schemas.AIAutomationRunnerCreate,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        rbac.require_admin(current_user, "Only administrators can register automation runners")
        if not rbac.has_permission(current_user, "read", payload.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        token = f"tmr_{secrets.token_urlsafe(32)}"
        runner = models.AIAutomationRunner(
            **payload.model_dump(),
            token_hash=_token_hash(token),
            token_prefix=token[:12],
            created_by=current_user.id,
            status="offline",
        )
        db.add(runner)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="A runner with this name already exists in the project") from exc
        db.refresh(runner)
        data = schemas.AIAutomationRunner.model_validate(runner).model_dump()
        return {**data, "token": token}

    @app.get("/ai-automation/runners", response_model=list[schemas.AIAutomationRunner])
    def list_ai_automation_runners(
        project_id: int = Query(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        if not rbac.has_permission(current_user, "read", project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return db.query(models.AIAutomationRunner).filter(
            models.AIAutomationRunner.project_id == project_id
        ).order_by(models.AIAutomationRunner.id).all()

    @app.post("/ai-automation/runners/{runner_id}/rotate-token", response_model=schemas.AIAutomationRunnerCreated)
    def rotate_ai_automation_runner_token(
        runner_id: int = Path(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        rbac.require_admin(current_user, "Only administrators can rotate automation runner tokens")
        runner = _get_runner(db, runner_id)
        token = f"tmr_{secrets.token_urlsafe(32)}"
        runner.token_hash = _token_hash(token)
        runner.token_prefix = token[:12]
        runner.status = "offline"
        db.commit()
        db.refresh(runner)
        data = schemas.AIAutomationRunner.model_validate(runner).model_dump()
        return {**data, "token": token}

    @app.delete("/ai-automation/runners/{runner_id}", response_model=schemas.AIAutomationRunner)
    def disable_ai_automation_runner(
        runner_id: int = Path(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        rbac.require_admin(current_user, "Only administrators can disable automation runners")
        runner = _get_runner(db, runner_id)
        runner.status = "disabled"
        db.commit()
        db.refresh(runner)
        return runner

    @app.post("/ai-automation/tasks", response_model=schemas.AIAutomationTask, status_code=201)
    def create_ai_automation_task(
        payload: schemas.AIAutomationTaskCreate,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        if not rbac.has_permission(current_user, "execute", payload.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        _validate_project_links(db, payload)
        task = models.AIAutomationTask(
            **payload.model_dump(),
            requested_by=current_user.id,
            status="queued",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @app.get("/ai-automation/tasks", response_model=list[schemas.AIAutomationTask])
    def list_ai_automation_tasks(
        project_id: int = Query(..., ge=1),
        status: str | None = Query(None, max_length=30),
        limit: int = Query(50, ge=1, le=200),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        if not rbac.has_permission(current_user, "read", project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        query = db.query(models.AIAutomationTask).filter(models.AIAutomationTask.project_id == project_id)
        if status:
            query = query.filter(models.AIAutomationTask.status == status.strip().lower())
        return query.order_by(models.AIAutomationTask.id.desc()).limit(limit).all()

    @app.get("/ai-automation/tasks/{task_id}", response_model=schemas.AIAutomationTask)
    def read_ai_automation_task(
        task_id: int = Path(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        task = _get_task(db, task_id)
        if not rbac.has_permission(current_user, "read", task.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return task

    @app.post("/ai-automation/tasks/{task_id}/cancel", response_model=schemas.AIAutomationTask)
    def cancel_ai_automation_task(
        task_id: int = Path(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        task = _get_task(db, task_id)
        if not rbac.has_permission(current_user, "execute", task.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        if task.status in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="Task is already in a terminal state")
        now = datetime.now(timezone.utc)
        task.cancel_requested_at = now
        if task.status == "queued":
            task.status = "cancelled"
            task.completed_at = now
        else:
            task.status = "cancel_requested"
        db.commit()
        db.refresh(task)
        return task

    @app.post("/internal/ai-automation/claim", response_model=schemas.AIAutomationTaskLease | None)
    def claim_ai_automation_task(
        response: Response,
        x_runner_token: str | None = Header(None, alias="X-Runner-Token"),
        db: Session = Depends(get_db),
    ):
        runner = _authenticate_runner(db, x_runner_token)
        now = datetime.now(timezone.utc)
        runner.status = "online"
        runner.last_seen_at = now
        task = db.query(models.AIAutomationTask).filter(
            models.AIAutomationTask.project_id == runner.project_id,
            models.AIAutomationTask.runner_type == runner.runner_type,
            or_(
                models.AIAutomationTask.status == "queued",
                (models.AIAutomationTask.status == "running")
                & (models.AIAutomationTask.lease_expires_at < now),
            ),
        ).order_by(models.AIAutomationTask.id).with_for_update(skip_locked=True).first()
        if task is None:
            db.commit()
            response.status_code = 204
            return None
        lease_token = secrets.token_urlsafe(32)
        task.runner_id = runner.id
        task.lease_token_hash = _token_hash(lease_token)
        task.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        task.attempt_count += 1
        task.status = "running"
        task.started_at = task.started_at or now
        db.commit()
        db.refresh(task)
        return {"task": task, "lease_token": lease_token}

    @app.post("/internal/ai-automation/heartbeat", response_model=schemas.AIAutomationRunnerHeartbeatResult)
    def heartbeat_ai_automation_runner(
        payload: schemas.AIAutomationRunnerHeartbeat,
        x_runner_token: str | None = Header(None, alias="X-Runner-Token"),
        db: Session = Depends(get_db),
    ):
        runner = _authenticate_runner(db, x_runner_token)
        now = datetime.now(timezone.utc)
        runner.status = "online"
        runner.last_seen_at = now
        cancel_requested = False
        lease_expires_at = None
        if payload.task_id is not None:
            if payload.lease_token is None:
                raise HTTPException(status_code=422, detail="lease_token is required when task_id is provided")
            task = _get_task(db, payload.task_id)
            _verify_lease(task, runner, payload.lease_token)
            cancel_requested = task.status == "cancel_requested"
            if not cancel_requested and task.status == "running":
                task.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
            lease_expires_at = task.lease_expires_at
        db.commit()
        return {
            "runner_status": runner.status,
            "cancel_requested": cancel_requested,
            "lease_expires_at": lease_expires_at,
        }

    @app.post("/internal/ai-automation/tasks/{task_id}/report", response_model=schemas.AIAutomationTask)
    def report_ai_automation_task(
        payload: schemas.AIAutomationTaskReport,
        task_id: int = Path(..., ge=1),
        x_runner_token: str | None = Header(None, alias="X-Runner-Token"),
        db: Session = Depends(get_db),
    ):
        runner = _authenticate_runner(db, x_runner_token)
        task = _get_task(db, task_id)
        _verify_lease(task, runner, payload.lease_token)
        if task.status in TERMINAL_STATUSES:
            if task.status != payload.status:
                raise HTTPException(status_code=409, detail="Task already has a different terminal result")
            return task
        if task.status not in {"running", "cancel_requested"}:
            raise HTTPException(status_code=409, detail="Task is not running")
        task.status = payload.status
        task.result = payload.result
        task.error_message = payload.error_message
        task.input_tokens = payload.input_tokens
        task.output_tokens = payload.output_tokens
        task.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(task)
        return task
