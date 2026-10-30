"""Credential references, batches, device locks, script drafts, and CI templates.

Runner-only routes depend on ``require_automation_runner``. Resolved credential
values are returned to the leased runner and are not written to audit metadata.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging

from fastapi import Depends, HTTPException, Path, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, rbac, schemas
from ..auth import get_current_active_user
from ..crypto import decrypt_data, encrypt_data
from ..database import get_db
from ..services.automation_ci import render_ci_templates
from ..services.automation_devices import acquire_lock, apply_offline_reclaim, release_lock
from ..services.automation_openapi_scripts import materialize_api_scripts
from ..services.automation_policy import enforce_task_policy, validate_credential_names
from ..services.mobile_mcp_discovery import IOS_DEPLOYMENT_NOTE, discovery_contract
from .ai_automation import (
    _audit_task_action,
    _get_task,
    _validate_project_links,
    _verify_lease,
    require_automation_runner,
)


logger = logging.getLogger(__name__)
OPEN_STATUSES = {"queued", "running", "cancel_requested"}


def _device_view(device: models.AIAutomationDevice) -> dict:
    note = IOS_DEPLOYMENT_NOTE if device.platform == "ios" else None
    data = schemas.AIAutomationDevice.model_validate(device).model_dump()
    data["deployment_note"] = note
    return data


def _batch_status(tasks: list[models.AIAutomationTask]) -> str:
    if not tasks:
        return "queued"
    if any(task.status in OPEN_STATUSES for task in tasks):
        return "running" if any(task.status == "running" for task in tasks) else "queued"
    return "completed"


def _batch_view(batch: models.AIAutomationBatch, tasks: list[models.AIAutomationTask]) -> dict:
    return {
        "id": batch.id,
        "project_id": batch.project_id,
        "runner_type": batch.runner_type,
        "execution_mode": batch.execution_mode,
        "idempotency_key": batch.idempotency_key,
        "environment_id": batch.environment_id,
        "task_ids": [task.id for task in tasks],
        "status": _batch_status(tasks),
        "created_at": batch.created_at,
    }


def _payload_hash(payload: schemas.AIAutomationBatchCreate) -> str:
    body = payload.model_dump(mode="json")
    body.pop("idempotency_key", None)
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _environment_type(db: Session, environment_id: int | None) -> str | None:
    if environment_id is None:
        return None
    environment = db.query(models.ExecutionEnvironment).filter(
        models.ExecutionEnvironment.id == environment_id
    ).first()
    if environment is None:
        raise HTTPException(status_code=400, detail="Environment must belong to the selected project")
    return environment.environment_type


def register_ai_automation_platform_routes(app) -> None:
    @app.post("/ai-automation/credentials", response_model=schemas.AIAutomationCredential, status_code=201)
    def create_ai_automation_credential(
        payload: schemas.AIAutomationCredentialCreate,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        if not rbac.has_permission(current_user, "execute", payload.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        credential = models.AIAutomationCredential(
            project_id=payload.project_id,
            name=payload.name,
            ciphertext=encrypt_data(payload.value),
            created_by=current_user.id,
        )
        db.add(credential)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="A credential with this name already exists") from exc
        db.refresh(credential)
        _audit_task_action(
            db, user_id=current_user.id, action="create", task_id=None, project_id=payload.project_id,
            description=f"AI automation credential reference '{payload.name}' stored",
            metadata={"actor_type": "user", "credential_ref": payload.name},
        )
        return credential

    @app.get("/ai-automation/credentials", response_model=list[schemas.AIAutomationCredential])
    def list_ai_automation_credentials(
        project_id: int = Query(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        if not rbac.has_permission(current_user, "read", project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return db.query(models.AIAutomationCredential).filter(
            models.AIAutomationCredential.project_id == project_id
        ).order_by(models.AIAutomationCredential.name).all()

    @app.delete("/ai-automation/credentials/{credential_id}", status_code=204)
    def delete_ai_automation_credential(
        credential_id: int = Path(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        credential = db.query(models.AIAutomationCredential).filter(
            models.AIAutomationCredential.id == credential_id
        ).first()
        if credential is None:
            raise HTTPException(status_code=404, detail="Credential reference not found")
        if not rbac.has_permission(current_user, "execute", credential.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        name = credential.name
        project_id = credential.project_id
        db.delete(credential)
        db.commit()
        _audit_task_action(
            db, user_id=current_user.id, action="delete", task_id=None, project_id=project_id,
            description=f"AI automation credential reference '{name}' deleted",
            metadata={"actor_type": "user", "credential_ref": name},
        )

    @app.post("/internal/ai-automation/tasks/{task_id}/credentials")
    def resolve_ai_automation_credentials(
        payload: schemas.AIAutomationCredentialResolve,
        task_id: int = Path(..., ge=1),
        db: Session = Depends(get_db),
        runner: models.AIAutomationRunner = Depends(require_automation_runner),
    ):
        task = _get_task(db, task_id)
        _verify_lease(task, runner, payload.lease_token)
        if task.project_id != runner.project_id:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        names = validate_credential_names(payload.names)
        config = task.config if isinstance(task.config, dict) else {}
        allowed = set(config.get("credential_refs") or [])
        auth = config.get("auth") if isinstance(config.get("auth"), dict) else {}
        if auth.get("credential_ref"):
            allowed.add(auth["credential_ref"])
        if any(name not in allowed for name in names):
            raise HTTPException(status_code=403, detail="Credential reference is not authorized for this task")
        rows = db.query(models.AIAutomationCredential).filter(
            models.AIAutomationCredential.project_id == task.project_id,
            models.AIAutomationCredential.name.in_(names),
        ).all()
        found = {row.name: row for row in rows}
        missing = [name for name in names if name not in found]
        if missing:
            raise HTTPException(status_code=404, detail="Credential reference was not found")
        resolved = {}
        for name in names:
            try:
                resolved[name] = decrypt_data(found[name].ciphertext)
            except Exception as exc:
                logger.warning("Credential reference %s could not be decrypted", name)
                raise HTTPException(status_code=500, detail="Credential reference could not be decrypted") from exc
        _audit_task_action(
            db, user_id=task.requested_by, action="execute", task_id=task.id, project_id=task.project_id,
            description=f"Runner resolved {len(names)} credential reference(s)",
            metadata={"actor_type": "runner", "runner_id": runner.id, "credential_refs": names},
        )
        return {"credentials": resolved}

    @app.post("/ai-automation/batches", response_model=schemas.AIAutomationBatch, status_code=201)
    def create_ai_automation_batch(
        payload: schemas.AIAutomationBatchCreate,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        if not rbac.has_permission(current_user, "execute", payload.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        if payload.environment_id is not None:
            _validate_project_links(db, schemas.AIAutomationTaskCreate(
                project_id=payload.project_id, runner_type=payload.runner_type, goal="batch",
                environment_id=payload.environment_id,
            ))
        environment_type = _environment_type(db, payload.environment_id)
        digest = _payload_hash(payload)
        existing = db.query(models.AIAutomationBatch).filter(
            models.AIAutomationBatch.project_id == payload.project_id,
            models.AIAutomationBatch.idempotency_key == payload.idempotency_key,
        ).first()
        if existing is not None:
            if existing.payload_hash != digest:
                raise HTTPException(status_code=409, detail="Idempotency key was already used for a different batch")
            tasks = db.query(models.AIAutomationTask).filter(
                models.AIAutomationTask.batch_id == existing.id
            ).order_by(models.AIAutomationTask.id).all()
            return _batch_view(existing, tasks)
        prepared = []
        for item in payload.items:
            if item.test_case_id is not None:
                _validate_project_links(db, schemas.AIAutomationTaskCreate(
                    project_id=payload.project_id, runner_type=payload.runner_type, goal=item.goal,
                    test_case_id=item.test_case_id, environment_id=payload.environment_id,
                ))
            config = dict(item.config)
            config["allowlist"] = payload.allowlist or config.get("allowlist") or {}
            enforce_task_policy(config, environment_type)
            prepared.append((item, config))
        batch = models.AIAutomationBatch(
            project_id=payload.project_id,
            idempotency_key=payload.idempotency_key,
            payload_hash=digest,
            runner_type=payload.runner_type,
            execution_mode=payload.execution_mode,
            environment_id=payload.environment_id,
            requested_by=current_user.id,
            allowlist=payload.allowlist,
        )
        db.add(batch)
        db.flush()
        tasks = []
        for item, config in prepared:
            task = models.AIAutomationTask(
                project_id=payload.project_id,
                test_case_id=item.test_case_id,
                environment_id=payload.environment_id,
                batch_id=batch.id,
                requested_by=current_user.id,
                runner_type=payload.runner_type,
                execution_mode=payload.execution_mode,
                goal=item.goal,
                config=config,
                status="queued",
            )
            db.add(task)
            tasks.append(task)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Batch idempotency key conflict") from exc
        for task in tasks:
            db.refresh(task)
        db.refresh(batch)
        _audit_task_action(
            db, user_id=current_user.id, action="create", task_id=None, project_id=payload.project_id,
            description=f"AI automation batch queued with {len(tasks)} tasks",
            metadata={"actor_type": "user", "batch_id": batch.id, "task_ids": [task.id for task in tasks]},
        )
        return _batch_view(batch, tasks)

    @app.get("/ai-automation/ci-templates")
    def read_ai_automation_ci_template(
        project_id: int = Query(..., ge=1),
        runner_type: str = Query("web"),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        if not rbac.has_permission(current_user, "read", project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        try:
            return render_ci_templates(project_id, runner_type.strip().lower())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/ai-automation/openapi-scripts")
    def create_openapi_runner_scripts(
        payload: schemas.AIAutomationOpenAPIScripts,
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        if not rbac.has_permission(current_user, "execute", payload.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        if payload.credential_ref:
            validate_credential_names([payload.credential_ref])
        generated = materialize_api_scripts(payload.document, payload.credential_ref)
        if not payload.create_tasks:
            return generated
        if not payload.idempotency_key:
            raise HTTPException(status_code=422, detail="idempotency_key is required when creating tasks")
        environment_type = _environment_type(db, payload.environment_id)
        items = []
        for script in generated["scripts"]:
            if script["requires_credential"]:
                generated["warnings"].append(f"{script['operation_key']}: credential reference required")
                continue
            config = {"script": script["script"], "allowlist": payload.allowlist}
            if script["credential_refs"]:
                config["credential_refs"] = script["credential_refs"]
                config["auth"] = script["auth"]
            try:
                enforce_task_policy(config, environment_type)
            except HTTPException as exc:
                generated["warnings"].append(f"{script['operation_key']}: {exc.detail}")
                continue
            items.append(schemas.AIAutomationBatchItem(goal=script["operation_key"], config=config))
        if not items:
            raise HTTPException(status_code=422, detail="No executable scripts were produced")
        batch_payload = schemas.AIAutomationBatchCreate(
            project_id=payload.project_id,
            runner_type="api",
            execution_mode="script",
            idempotency_key=payload.idempotency_key,
            environment_id=payload.environment_id,
            allowlist=payload.allowlist,
            items=items,
        )
        created = create_ai_automation_batch(batch_payload, db, current_user)
        return {**generated, "batch": created}

    @app.post("/internal/ai-automation/devices/heartbeat", response_model=list[schemas.AIAutomationDevice])
    def heartbeat_ai_automation_devices(
        payload: schemas.AIAutomationDeviceHeartbeat,
        db: Session = Depends(get_db),
        runner: models.AIAutomationRunner = Depends(require_automation_runner),
    ):
        if runner.runner_type != "mobile":
            raise HTTPException(status_code=409, detail="Only mobile runners can register devices")
        now = datetime.now(timezone.utc)
        views = []
        for item in payload.devices:
            device = db.query(models.AIAutomationDevice).filter(
                models.AIAutomationDevice.project_id == runner.project_id,
                models.AIAutomationDevice.external_id == item.external_id.strip(),
            ).first()
            if device is None:
                device = models.AIAutomationDevice(
                    project_id=runner.project_id,
                    external_id=item.external_id.strip(),
                    platform=item.platform,
                    name=item.name.strip(),
                    capabilities=item.capabilities,
                    runner_id=runner.id,
                    status="online",
                    last_seen_at=now,
                )
                db.add(device)
            else:
                device.platform = item.platform
                device.name = item.name.strip()
                device.capabilities = item.capabilities
                device.runner_id = runner.id
                device.last_seen_at = now
                if device.status != "locked":
                    device.status = "online"
            views.append(device)
        db.commit()
        for device in views:
            db.refresh(device)
        return [_device_view(device) for device in views]

    @app.get("/ai-automation/devices", response_model=list[schemas.AIAutomationDevice])
    def list_ai_automation_devices(
        project_id: int = Query(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        if not rbac.has_permission(current_user, "read", project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        now = datetime.now(timezone.utc)
        devices = db.query(models.AIAutomationDevice).filter(
            models.AIAutomationDevice.project_id == project_id
        ).order_by(models.AIAutomationDevice.id).all()
        if any(apply_offline_reclaim(device, now) for device in devices):
            db.commit()
        return [_device_view(device) for device in devices]

    @app.post("/ai-automation/devices/reclaim", response_model=list[schemas.AIAutomationDevice])
    def reclaim_ai_automation_devices(
        project_id: int = Query(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        if not rbac.has_permission(current_user, "execute", project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        now = datetime.now(timezone.utc)
        devices = db.query(models.AIAutomationDevice).filter(
            models.AIAutomationDevice.project_id == project_id
        ).all()
        reclaimed = [device for device in devices if apply_offline_reclaim(device, now)]
        db.commit()
        for device in reclaimed:
            db.refresh(device)
        _audit_task_action(
            db, user_id=current_user.id, action="update", task_id=None, project_id=project_id,
            description=f"Reclaimed {len(reclaimed)} offline automation device lock(s)",
            metadata={"actor_type": "user", "device_ids": [device.id for device in reclaimed]},
        )
        return [_device_view(device) for device in reclaimed]

    @app.post("/internal/ai-automation/devices/{device_id}/lock", response_model=schemas.AIAutomationDevice)
    def lock_ai_automation_device(
        payload: schemas.AIAutomationDeviceLock,
        device_id: int = Path(..., ge=1),
        db: Session = Depends(get_db),
        runner: models.AIAutomationRunner = Depends(require_automation_runner),
    ):
        device = db.query(models.AIAutomationDevice).filter(models.AIAutomationDevice.id == device_id).first()
        if device is None or device.project_id != runner.project_id:
            raise HTTPException(status_code=404, detail="Device not found")
        task = _get_task(db, payload.task_id)
        _verify_lease(task, runner, payload.lease_token)
        if task.project_id != device.project_id:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        try:
            acquire_lock(device, task_id=task.id, runner_id=runner.id, now=datetime.now(timezone.utc))
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit()
        db.refresh(device)
        return _device_view(device)

    @app.post("/internal/ai-automation/devices/{device_id}/unlock", response_model=schemas.AIAutomationDevice)
    def unlock_ai_automation_device(
        payload: schemas.AIAutomationDeviceLock,
        device_id: int = Path(..., ge=1),
        db: Session = Depends(get_db),
        runner: models.AIAutomationRunner = Depends(require_automation_runner),
    ):
        device = db.query(models.AIAutomationDevice).filter(models.AIAutomationDevice.id == device_id).first()
        if device is None or device.project_id != runner.project_id:
            raise HTTPException(status_code=404, detail="Device not found")
        task = _get_task(db, payload.task_id)
        _verify_lease(task, runner, payload.lease_token)
        try:
            release_lock(device, task_id=task.id, runner_id=runner.id)
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit()
        db.refresh(device)
        return _device_view(device)

    @app.get("/ai-automation/mobile-mcp/discovery")
    def read_mobile_mcp_discovery(
        project_id: int = Query(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        if not rbac.has_permission(current_user, "read", project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return discovery_contract(None)

    @app.post(
        "/ai-automation/tasks/{task_id}/script-drafts",
        response_model=schemas.AIAutomationScriptDraft,
        status_code=201,
    )
    def create_ai_automation_script_draft(
        payload: schemas.AIAutomationScriptDraftCreate,
        task_id: int = Path(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        task = _get_task(db, task_id)
        if not rbac.has_permission(current_user, "execute", task.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        current = db.query(models.AIAutomationScriptDraft.revision).filter(
            models.AIAutomationScriptDraft.source_task_id == task.id
        ).order_by(models.AIAutomationScriptDraft.revision.desc()).first()
        revision = (current[0] if current else 0) + 1
        draft = models.AIAutomationScriptDraft(
            project_id=task.project_id,
            source_task_id=task.id,
            environment_id=task.environment_id,
            revision=revision,
            source=payload.source,
            status="draft",
            script=payload.script,
            note=payload.note,
            created_by=current_user.id,
        )
        db.add(draft)
        db.commit()
        db.refresh(draft)
        _audit_task_action(
            db, user_id=current_user.id, action="create", task_id=task.id, project_id=task.project_id,
            description=f"AI automation script draft revision {revision} saved",
            metadata={"actor_type": "user", "source": payload.source, "environment_id": task.environment_id, "draft_id": draft.id},
        )
        return draft

    @app.post("/ai-automation/script-drafts/{draft_id}/approve", response_model=schemas.AIAutomationScriptDraft)
    def approve_ai_automation_script_draft(
        draft_id: int = Path(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        draft = db.query(models.AIAutomationScriptDraft).filter(models.AIAutomationScriptDraft.id == draft_id).first()
        if draft is None:
            raise HTTPException(status_code=404, detail="Script draft not found")
        if not rbac.has_permission(current_user, "execute", draft.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        if draft.status != "draft":
            raise HTTPException(status_code=409, detail="Only a draft can be approved")
        draft.status = "approved"
        draft.approved_by = current_user.id
        draft.approved_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(draft)
        _audit_task_action(
            db, user_id=current_user.id, action="update", task_id=draft.source_task_id, project_id=draft.project_id,
            description=f"AI automation script draft {draft.id} approved",
            metadata={"actor_type": "user", "draft_id": draft.id, "revision": draft.revision},
        )
        return draft

    @app.post("/ai-automation/tasks/{task_id}/retry", response_model=schemas.AIAutomationTask)
    def retry_ai_automation_task(
        task_id: int = Path(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        task = _get_task(db, task_id)
        if not rbac.has_permission(current_user, "execute", task.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        open_child = db.query(models.AIAutomationTask).filter(
            models.AIAutomationTask.retry_of_id == task.id,
            models.AIAutomationTask.status.in_(tuple(OPEN_STATUSES)),
        ).order_by(models.AIAutomationTask.id.desc()).first()
        if open_child is not None:
            return open_child
        if task.status not in {"failed", "timed_out", "blocked"}:
            raise HTTPException(status_code=409, detail="Only a failed, timed out, or blocked task can be retried")
        child = models.AIAutomationTask(
            project_id=task.project_id,
            test_case_id=task.test_case_id,
            test_run_id=task.test_run_id,
            environment_id=task.environment_id,
            retry_of_id=task.id,
            requested_by=current_user.id,
            runner_type=task.runner_type,
            execution_mode=task.execution_mode,
            goal=task.goal,
            max_steps=task.max_steps,
            timeout_seconds=task.timeout_seconds,
            token_budget=task.token_budget,
            config=task.config or {},
            status="queued",
        )
        db.add(child)
        db.commit()
        db.refresh(child)
        _audit_task_action(
            db, user_id=current_user.id, action="create", task_id=child.id, project_id=child.project_id,
            description=f"AI automation task retry queued from task {task.id}",
            metadata={"actor_type": "user", "retry_of_id": task.id},
        )
        return child

    @app.get("/ai-automation/tasks/{task_id}/budget-alerts", response_model=list[schemas.AIAutomationBudgetAlert])
    def list_ai_automation_budget_alerts(
        task_id: int = Path(..., ge=1),
        db: Session = Depends(get_db),
        current_user: schemas.User = Depends(get_current_active_user),
    ):
        task = _get_task(db, task_id)
        if not rbac.has_permission(current_user, "read", task.project_id, db):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return db.query(models.AIAutomationBudgetAlert).filter(
            models.AIAutomationBudgetAlert.task_id == task.id
        ).order_by(models.AIAutomationBudgetAlert.id).all()
