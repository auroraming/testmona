"""Credential refs, batches, device locks, drafts, and assertion archival."""

from datetime import datetime, timedelta, timezone

from conftest import make_http_client


client = make_http_client()
SECRET = "runner-only-secret-value"


def _runner(client, runner_type="api", name=None):
    response = client.post("/ai-automation/runners", json={
        "project_id": client.project_id,
        "name": name or f"{runner_type}-platform",
        "runner_type": runner_type,
    })
    assert response.status_code == 201, response.text
    data = response.json()
    token = data.pop("token")
    return data, token


def test_credential_reference_is_encrypted_and_resolved_only_for_the_lease(client):
    created = client.post("/ai-automation/credentials", json={
        "project_id": client.project_id, "name": "api-token", "value": SECRET,
    })
    assert created.status_code == 201, created.text
    assert SECRET not in created.text
    listed = client.get("/ai-automation/credentials", params={"project_id": client.project_id})
    assert listed.status_code == 200, listed.text
    assert SECRET not in listed.text
    assert listed.json()[0]["name"] == "api-token"

    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "api",
        "execution_mode": "script",
        "goal": "Call health",
        "config": {
            "credential_refs": ["api-token"],
            "auth": {"type": "bearer", "credential_ref": "api-token"},
            "script": [{"action": "request", "method": "GET", "path": "/health"}],
        },
    })
    assert task.status_code == 201, task.text
    _, token = _runner(client)
    lease = client.post("/internal/ai-automation/claim", headers={"X-Runner-Token": token}).json()
    resolved = client.post(
        f"/internal/ai-automation/tasks/{task.json()['id']}/credentials",
        headers={"X-Runner-Token": token},
        json={"lease_token": lease["lease_token"], "names": ["api-token"]},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["credentials"]["api-token"] == SECRET
    denied = client.post(
        f"/internal/ai-automation/tasks/{task.json()['id']}/credentials",
        headers={"X-Runner-Token": token},
        json={"lease_token": lease["lease_token"], "names": ["other-token"]},
    )
    assert denied.status_code == 403

    from app import models
    with client.SessionLocal() as db:
        row = db.query(models.AIAutomationCredential).one()
        assert SECRET not in row.ciphertext
        audits = db.query(models.AuditTrail).filter(models.AuditTrail.project_id == client.project_id).all()
        assert all(SECRET not in str(item.additional_metadata) and SECRET not in (item.description or "") for item in audits)


def test_passed_report_without_assertions_is_archived_as_failed(client):
    _, token = _runner(client, "web", "web-archive")
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id, "runner_type": "web", "goal": "Click around", "token_budget": 100,
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    report = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/report",
        headers=headers,
        json={"lease_token": lease["lease_token"], "status": "passed", "input_tokens": 90, "output_tokens": 20},
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["status"] == "failed"
    assert body["result"]["archive_reason"] == "missing_assertion"
    assert body["result"]["runner_reported_status"] == "passed"
    alerts = client.get(f"/ai-automation/tasks/{task['id']}/budget-alerts")
    assert alerts.status_code == 200, alerts.text
    assert alerts.json()[0]["level"] == "exceeded"
    assert alerts.json()[0]["estimated_cost_micros"] is None
    repeated = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/report",
        headers=headers,
        json={"lease_token": lease["lease_token"], "status": "passed", "input_tokens": 90, "output_tokens": 20},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["status"] == "failed"


def test_expired_lease_does_not_create_a_second_execution(client):
    _, token = _runner(client, "web", "web-lease")
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id, "runner_type": "web", "goal": "One attempt",
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers)
    assert lease.status_code == 200, lease.text
    from app import models
    with client.SessionLocal() as db:
        row = db.query(models.AIAutomationTask).filter(models.AIAutomationTask.id == task["id"]).one()
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        db.commit()
    queued = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id, "runner_type": "web", "goal": "Next",
    }).json()
    again = client.post("/internal/ai-automation/claim", headers=headers)
    assert again.status_code == 200, again.text
    assert again.json()["task"]["id"] == queued["id"]
    current = client.get(f"/ai-automation/tasks/{task['id']}")
    assert current.json()["status"] == "timed_out"
    assert current.json()["attempt_count"] == 1
    retry = client.post(f"/ai-automation/tasks/{task['id']}/retry")
    assert retry.status_code == 200, retry.text
    assert retry.json()["retry_of_id"] == task["id"]
    assert retry.json()["status"] == "queued"
    again_retry = client.post(f"/ai-automation/tasks/{task['id']}/retry")
    assert again_retry.json()["id"] == retry.json()["id"]


def test_batch_is_idempotent_and_ci_template_has_no_secret(client):
    payload = {
        "project_id": client.project_id,
        "runner_type": "web",
        "execution_mode": "script",
        "idempotency_key": "batch-key-001",
        "allowlist": {"origins": ["https://staging.example.test"]},
        "items": [{
            "goal": "Open staging",
            "config": {"script": [{"action": "navigate", "url": "https://staging.example.test/"}]},
        }],
    }
    first = client.post("/ai-automation/batches", json=payload)
    assert first.status_code == 201, first.text
    second = client.post("/ai-automation/batches", json=payload)
    assert second.status_code == 201, second.text
    assert second.json()["task_ids"] == first.json()["task_ids"]
    changed = dict(payload)
    changed["items"] = [{**payload["items"][0], "goal": "Different"}]
    conflict = client.post("/ai-automation/batches", json=changed)
    assert conflict.status_code == 409
    template = client.get("/ai-automation/ci-templates", params={"project_id": client.project_id, "runner_type": "web"})
    assert template.status_code == 200, template.text
    assert "TESTMONA_API_TOKEN" in template.json()["github_actions"]
    assert SECRET not in template.text
    assert "does not mean the run passed" in template.json()["curl"] or "explicit assertions" in template.json()["note"]


def test_production_and_payment_targets_are_rejected(client):
    from app import models
    with client.SessionLocal() as db:
        environment = models.ExecutionEnvironment(
            name="Prod", project_id=client.project_id, environment_type="production", config_data={},
        )
        db.add(environment)
        db.commit()
        environment_id = environment.id
    denied = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id, "runner_type": "api", "goal": "Prod", "environment_id": environment_id,
    })
    assert denied.status_code == 403
    payment = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "api",
        "goal": "Charge",
        "config": {"base_url": "https://payments.example.test"},
    })
    assert payment.status_code == 403


def test_device_inventory_lock_and_offline_reclaim(client):
    runner, token = _runner(client, "mobile", "mobile-devices")
    headers = {"X-Runner-Token": token}
    registered = client.post("/internal/ai-automation/devices/heartbeat", headers=headers, json={"devices": [{
        "external_id": "emulator-5554", "platform": "android", "name": "Pixel", "capabilities": {"sdk": 34},
    }, {
        "external_id": "ios-sim", "platform": "ios", "name": "iPhone", "capabilities": {},
    }]})
    assert registered.status_code == 200, registered.text
    android = next(item for item in registered.json() if item["platform"] == "android")
    ios = next(item for item in registered.json() if item["platform"] == "ios")
    assert "Xcode" in ios["deployment_note"]
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id, "runner_type": "mobile", "goal": "Open app",
    }).json()
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    locked = client.post(
        f"/internal/ai-automation/devices/{android['id']}/lock",
        headers=headers,
        json={"lease_token": lease["lease_token"], "task_id": task["id"]},
    )
    assert locked.status_code == 200, locked.text
    assert locked.json()["status"] == "locked"
    other, other_token = _runner(client, "mobile", "mobile-other")
    other_task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id, "runner_type": "mobile", "goal": "Second",
    }).json()
    # The first task holds the only queued slot, so finish it before the other runner can claim.
    client.post(
        f"/internal/ai-automation/tasks/{task['id']}/report",
        headers=headers,
        json={"lease_token": lease["lease_token"], "status": "blocked"},
    )
    other_lease = client.post("/internal/ai-automation/claim", headers={"X-Runner-Token": other_token}).json()
    conflict = client.post(
        f"/internal/ai-automation/devices/{android['id']}/lock",
        headers={"X-Runner-Token": other_token},
        json={"lease_token": other_lease["lease_token"], "task_id": other_task["id"]},
    )
    assert conflict.status_code == 409, conflict.text
    from app import models
    with client.SessionLocal() as db:
        row = db.query(models.AIAutomationDevice).filter(models.AIAutomationDevice.id == android["id"]).one()
        row.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()
    reclaimed = client.post("/ai-automation/devices/reclaim", params={"project_id": client.project_id})
    assert reclaimed.status_code == 200, reclaimed.text
    recovered = next(item for item in reclaimed.json() if item["id"] == android["id"])
    assert recovered["status"] == "offline"
    assert recovered["lock_task_id"] is None
    discovery = client.get("/ai-automation/mobile-mcp/discovery", params={"project_id": client.project_id})
    assert discovery.status_code == 200, discovery.text
    assert discovery.json()["live"] is False
    assert "mobile_install_app" not in discovery.json()["tools"]
    assert runner["id"] != other["id"]


def test_failure_suggestion_confirmation_does_not_create_a_defect(client):
    from app import models

    _, token = _runner(client, "api", "api-failure")
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id, "runner_type": "api", "goal": "Read orders",
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    evidence = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/evidence",
        headers=headers,
        json={"lease_token": lease["lease_token"], "items": [
            {
                "sequence": 1, "evidence_type": "network", "title": "GET /orders", "status": "completed",
                "payload": {"method": "GET", "url": "https://user:secretpass@staging.example.test/orders?token=abcdef", "status": 500},
            },
            {
                "sequence": 2, "evidence_type": "assertion", "title": "status", "status": "failed",
                "payload": {"assertion": {"passed": False, "expected": 200, "actual": 500}},
            },
            {
                "sequence": 3, "evidence_type": "log", "title": "note",
                "payload": {"message": "Bearer runner-only-secret-value observed"},
            },
        ]},
    )
    assert evidence.status_code == 200, evidence.text
    stored = evidence.json()
    assert "secretpass" not in str(stored)
    assert "runner-only-secret-value" not in str(stored)
    assert "Bearer [redacted]" in str(stored)
    report = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/report",
        headers=headers,
        json={
            "lease_token": lease["lease_token"], "status": "failed",
            "input_tokens": 12, "cached_tokens": 4, "output_tokens": 3,
        },
    )
    assert report.status_code == 200, report.text
    suggestion = client.get(f"/ai-automation/tasks/{task['id']}/failure-suggestion")
    assert suggestion.status_code == 200, suggestion.text
    assert suggestion.json()["category"] == "upstream_error"
    assert "does not create or link a defect" in suggestion.json()["summary"]
    assert "secretpass" not in suggestion.text
    with client.SessionLocal() as db:
        defects_before = db.query(models.Defect).count()
    confirmed = client.post(f"/ai-automation/failure-suggestions/{suggestion.json()['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    with client.SessionLocal() as db:
        assert db.query(models.Defect).count() == defects_before
    usage = client.get(f"/ai-automation/tasks/{task['id']}/token-usage")
    assert usage.status_code == 200, usage.text
    assert usage.json()[0]["input_tokens"] == 12
    assert usage.json()[0]["cached_tokens"] == 4
    assert usage.json()[0]["output_tokens"] == 3
    assert usage.json()[0]["estimated_cost_micros"] is None
    repeated = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/report",
        headers=headers,
        json={"lease_token": lease["lease_token"], "status": "failed", "input_tokens": 12, "cached_tokens": 4, "output_tokens": 3},
    )
    assert repeated.status_code == 200, repeated.text
    assert len(client.get(f"/ai-automation/tasks/{task['id']}/token-usage").json()) == 1


def test_cancel_expiry_and_runner_concurrency_do_not_duplicate_work(client):
    _, token = _runner(client, "web", "web-capacity")
    headers = {"X-Runner-Token": token}
    first = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id, "runner_type": "web", "goal": "First",
    }).json()
    second = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id, "runner_type": "web", "goal": "Second",
    }).json()
    lease = client.post("/internal/ai-automation/claim", headers=headers)
    assert lease.status_code == 200, lease.text
    assert lease.json()["task"]["id"] == first["id"]
    blocked = client.post("/internal/ai-automation/claim", headers=headers)
    assert blocked.status_code == 204, blocked.text
    client.post(f"/ai-automation/tasks/{first['id']}/cancel")
    from datetime import datetime, timedelta, timezone
    from app import models
    with client.SessionLocal() as db:
        row = db.query(models.AIAutomationTask).filter(models.AIAutomationTask.id == first["id"]).one()
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        db.commit()
    recovered = client.post("/internal/ai-automation/claim", headers=headers)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["task"]["id"] == second["id"]
    assert client.get(f"/ai-automation/tasks/{first['id']}").json()["status"] == "cancelled"
    assert client.get(f"/ai-automation/tasks/{first['id']}").json()["attempt_count"] == 1


def test_evidence_becomes_a_script_draft_and_rollback_does_not_execute(client):
    _, token = _runner(client, "web", "web-draft")
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id, "runner_type": "web", "execution_mode": "ai", "goal": "Explore login",
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    secret = "super-secret-token-value"
    evidence = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/evidence",
        headers=headers,
        json={"lease_token": lease["lease_token"], "items": [
            {"sequence": 1, "evidence_type": "step", "title": "navigate", "payload": {"tool": "browser_navigate", "url": f"https://user:{secret}@staging.example.test/login"}},
            {"sequence": 2, "evidence_type": "step", "title": "fill", "payload": {"action": "fill", "selector": "#password", "value": secret}},
            {"sequence": 3, "evidence_type": "assertion", "title": "visible", "status": "passed", "payload": {"action": "assert_visible", "selector": "#home"}},
        ]},
    )
    assert evidence.status_code == 200, evidence.text
    assert secret not in evidence.text
    before = client.get("/ai-automation/tasks", params={"project_id": client.project_id}).json()
    draft = client.post(f"/ai-automation/tasks/{task['id']}/script-drafts/from-evidence")
    assert draft.status_code == 201, draft.text
    body = draft.json()
    assert body["status"] == "draft"
    assert body["source"] == "exploration"
    assert secret not in str(body)
    assert body["script"][0]["url"] == "https://staging.example.test/login"
    assert body["script"][1]["value"] == "[redacted]"
    rolled = client.post(f"/ai-automation/script-drafts/{body['id']}/rollback")
    assert rolled.status_code == 201, rolled.text
    assert rolled.json()["revision"] == 2
    assert rolled.json()["status"] == "draft"
    after = client.get("/ai-automation/tasks", params={"project_id": client.project_id}).json()
    assert [item["id"] for item in after] == [item["id"] for item in before]


def test_openapi_scripts_and_draft_approval_do_not_auto_execute(client):
    document = {
        "openapi": "3.0.3",
        "info": {"title": "Demo", "version": "1"},
        "paths": {"/health": {"get": {
            "parameters": [{"name": "password", "in": "query", "example": SECRET}],
            "responses": {"200": {"description": "ok"}},
        }}},
    }
    preview = client.post("/ai-automation/openapi-scripts", json={
        "project_id": client.project_id, "document": document,
    })
    assert preview.status_code == 200, preview.text
    assert SECRET not in preview.text
    assert preview.json()["scripts"][0]["script"][1]["action"] == "assert_status"
    created = client.post("/ai-automation/openapi-scripts", json={
        "project_id": client.project_id,
        "document": document,
        "create_tasks": True,
        "idempotency_key": "openapi-batch-01",
        "allowlist": {"origins": ["https://staging.example.test"]},
    })
    assert created.status_code == 200, created.text
    assert created.json()["batch"]["task_ids"]
    task_id = created.json()["batch"]["task_ids"][0]
    before = client.get("/ai-automation/tasks", params={"project_id": client.project_id}).json()
    draft = client.post(f"/ai-automation/tasks/{task_id}/script-drafts", json={
        "source": "openapi",
        "script": preview.json()["scripts"][0]["script"],
        "note": "Reviewed health check",
    })
    assert draft.status_code == 201, draft.text
    assert draft.json()["revision"] == 1
    assert draft.json()["status"] == "draft"
    approved = client.post(f"/ai-automation/script-drafts/{draft.json()['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    after = client.get("/ai-automation/tasks", params={"project_id": client.project_id}).json()
    assert [item["id"] for item in after] == [item["id"] for item in before]
    assert client.post("/ai-automation/script-drafts/999999/enqueue").status_code == 404
    queued = client.post(f"/ai-automation/script-drafts/{draft.json()['id']}/enqueue")
    assert queued.status_code == 200, queued.text
    assert queued.json()["execution_mode"] == "script"
    assert queued.json()["config"]["script_draft_id"] == draft.json()["id"]
    assert queued.json()["config"]["script"][0]["action"] == "request"
    repeated = client.post(f"/ai-automation/script-drafts/{draft.json()['id']}/enqueue")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["id"] == queued.json()["id"]
