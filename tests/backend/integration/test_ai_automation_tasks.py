"""AI automation tasks are project-scoped, cancellable, and secret-safe."""

from conftest import make_http_client


client = make_http_client()


def test_create_list_read_and_cancel_task(client):
    created = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "web",
        "execution_mode": "ai",
        "goal": "Verify the login page",
        "max_steps": 20,
        "timeout_seconds": 300,
        "token_budget": 5000,
        "config": {"base_url": "https://example.test", "credential_ref": "login-user"},
    })
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "queued"
    assert task["runner_type"] == "web"

    listed = client.get("/ai-automation/tasks", params={"project_id": client.project_id})
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [task["id"]]

    read = client.get(f"/ai-automation/tasks/{task['id']}")
    assert read.status_code == 200, read.text

    cancelled = client.post(f"/ai-automation/tasks/{task['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancel_requested_at"] is not None
    assert cancelled.json()["completed_at"] is not None

    repeated = client.post(f"/ai-automation/tasks/{task['id']}/cancel")
    assert repeated.status_code == 409


def test_create_rejects_inline_secrets(client):
    response = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "api",
        "goal": "Check health",
        "config": {"headers": {"X-API-Key": "secret-value"}},
    })
    assert response.status_code == 422
    assert "credential references" in response.text


def test_create_rejects_cross_project_test_case(client):
    other_project = client.post("/projects", json={"name": "Other"}).json()
    suite = client.post("/test-suites", json={"name": "Other suite", "project_id": other_project["id"]}).json()
    test_case = client.post("/test-cases", json={
        "title": "Other case",
        "test_suite_id": suite["id"],
        "priority": "medium",
        "test_type": "manual",
    }).json()
    response = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "api",
        "goal": "Run another project's case",
        "test_case_id": test_case["id"],
    })
    assert response.status_code == 400
    assert "selected project" in response.json()["detail"]


def test_project_outsider_cannot_read_or_create_tasks(client):
    from app import models

    created = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "mobile",
        "goal": "Open the app",
    }).json()
    with client.SessionLocal() as db:
        outsider = models.User(
            username="ai-task-outsider",
            email="ai-task-outsider@example.com",
            hashed_password="x",
            role="user",
            is_active=True,
            full_name="AI Task Outsider",
        )
        db.add(outsider)
        db.commit()
        db.refresh(outsider)
        outsider_id = outsider.id

    client.set_current_user(outsider_id)
    assert client.get(f"/ai-automation/tasks/{created['id']}").status_code == 403
    assert client.get("/ai-automation/tasks", params={"project_id": client.project_id}).status_code == 403
    assert client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "web",
        "goal": "Unauthorized",
    }).status_code == 403


def _register_runner(client, runner_type: str = "web") -> tuple[dict, str]:
    response = client.post("/ai-automation/runners", json={
        "project_id": client.project_id,
        "name": f"{runner_type}-runner",
        "runner_type": runner_type,
        "capabilities": {"browser": "chromium"} if runner_type == "web" else {},
    })
    assert response.status_code == 201, response.text
    data = response.json()
    token = data.pop("token")
    return data, token


def test_runner_claim_heartbeat_report_and_idempotency(client):
    runner, token = _register_runner(client)
    created = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "web",
        "goal": "Verify home page",
    }).json()
    headers = {"X-Runner-Token": token}

    claim = client.post("/internal/ai-automation/claim", headers=headers)
    assert claim.status_code == 200, claim.text
    lease = claim.json()
    assert lease["task"]["id"] == created["id"]
    assert lease["task"]["runner_id"] == runner["id"]
    assert lease["task"]["status"] == "running"
    assert lease["task"]["attempt_count"] == 1

    heartbeat = client.post("/internal/ai-automation/heartbeat", headers=headers, json={
        "task_id": created["id"],
        "lease_token": lease["lease_token"],
    })
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["cancel_requested"] is False
    assert heartbeat.json()["lease_expires_at"] is not None

    report_payload = {
        "lease_token": lease["lease_token"],
        "status": "passed",
        "result": {"assertions": [{"name": "title", "passed": True}]},
        "input_tokens": 100,
        "output_tokens": 20,
    }
    report = client.post(
        f"/internal/ai-automation/tasks/{created['id']}/report",
        headers=headers,
        json=report_payload,
    )
    assert report.status_code == 200, report.text
    assert report.json()["status"] == "passed"
    assert report.json()["input_tokens"] == 100

    repeated = client.post(
        f"/internal/ai-automation/tasks/{created['id']}/report",
        headers=headers,
        json=report_payload,
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["status"] == "passed"

    empty = client.post("/internal/ai-automation/claim", headers=headers)
    assert empty.status_code == 204


def test_running_task_receives_cancel_signal(client):
    _, token = _register_runner(client, "api")
    created = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "api",
        "goal": "Check health endpoint",
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()

    cancelled = client.post(f"/ai-automation/tasks/{created['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancel_requested"

    heartbeat = client.post("/internal/ai-automation/heartbeat", headers=headers, json={
        "task_id": created["id"],
        "lease_token": lease["lease_token"],
    })
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["cancel_requested"] is True

    report = client.post(
        f"/internal/ai-automation/tasks/{created['id']}/report",
        headers=headers,
        json={"lease_token": lease["lease_token"], "status": "cancelled"},
    )
    assert report.status_code == 200, report.text
    assert report.json()["status"] == "cancelled"


def test_runner_endpoints_reject_invalid_token(client):
    response = client.post(
        "/internal/ai-automation/claim",
        headers={"X-Runner-Token": "tmr_invalid-token-value"},
    )
    assert response.status_code == 401


def test_runner_token_rotation_and_disable_revoke_access(client):
    runner, old_token = _register_runner(client)
    rotated = client.post(f"/ai-automation/runners/{runner['id']}/rotate-token")
    assert rotated.status_code == 200, rotated.text
    new_token = rotated.json()["token"]
    assert new_token != old_token
    assert client.post(
        "/internal/ai-automation/claim",
        headers={"X-Runner-Token": old_token},
    ).status_code == 401
    assert client.post(
        "/internal/ai-automation/claim",
        headers={"X-Runner-Token": new_token},
    ).status_code == 204

    disabled = client.delete(f"/ai-automation/runners/{runner['id']}")
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"
    assert client.post(
        "/internal/ai-automation/claim",
        headers={"X-Runner-Token": new_token},
    ).status_code == 401
