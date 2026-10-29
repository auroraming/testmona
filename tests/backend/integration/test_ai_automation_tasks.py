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
    assert lease["context"] == {"goal": "Verify home page", "config": {}}

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


def test_runner_claim_includes_safe_test_case_and_environment_context(client):
    from app import models

    with client.SessionLocal() as db:
        suite = models.TestSuite(name="Checkout", project_id=client.project_id)
        db.add(suite)
        db.flush()
        case = models.TestCase(
            title="Submit order", test_suite_id=suite.id, project_id=client.project_id,
            description="Checkout flow", preconditions="Cart has one item", priority="high",
        )
        db.add(case)
        db.flush()
        db.add(models.TestCaseStep(
            test_case_id=case.id, step_number=1, order_index=0, action="Click submit",
            expected_result="Confirmation is visible", data={"password": "must-not-leak"},
        ))
        environment = models.ExecutionEnvironment(
            name="Staging", project_id=client.project_id, environment_type="staging",
            config_data={
                "base_url": "https://staging.example.test",
                "api_key": "must-not-leak",
                "headers": {"Authorization": "must-not-leak"},
            },
        )
        db.add(environment)
        db.commit()
        case_id, environment_id = case.id, environment.id

    _, token = _register_runner(client)
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "web",
        "goal": "Run checkout",
        "test_case_id": case_id,
        "environment_id": environment_id,
    })
    assert task.status_code == 201, task.text
    lease = client.post(
        "/internal/ai-automation/claim", headers={"X-Runner-Token": token}
    ).json()

    assert lease["context"]["test_case"]["title"] == "Submit order"
    assert lease["context"]["test_case"]["structured_steps"] == [{
        "step_number": 1,
        "action": "Click submit",
        "expected_result": "Confirmation is visible",
        "step_type": "manual",
    }]
    assert lease["context"]["environment"]["config"] == {
        "base_url": "https://staging.example.test"
    }
    assert "must-not-leak" not in str(lease["context"])

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


def test_runner_appends_ordered_idempotent_evidence(client):
    _, token = _register_runner(client)
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "web",
        "goal": "Capture evidence",
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    payload = {
        "lease_token": lease["lease_token"],
        "items": [
            {
                "sequence": 2,
                "evidence_type": "assertion",
                "title": "Login succeeded",
                "status": "passed",
                "payload": {"expected": "dashboard", "actual": "dashboard"},
            },
            {
                "sequence": 1,
                "evidence_type": "screenshot",
                "title": "Login form",
                "payload": {"mime_type": "image/png"},
                "artifact_ref": "ai-tasks/1/login.png",
            },
        ],
    }
    first = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/evidence",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 200, first.text
    assert [item["sequence"] for item in first.json()] == [1, 2]

    repeated = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/evidence",
        headers=headers,
        json=payload,
    )
    assert repeated.status_code == 200, repeated.text
    assert [item["id"] for item in repeated.json()] == [item["id"] for item in first.json()]

    listed = client.get(f"/ai-automation/tasks/{task['id']}/evidence")
    assert listed.status_code == 200, listed.text
    assert [item["sequence"] for item in listed.json()] == [1, 2]

    conflict = payload.copy()
    conflict["items"] = [{
        "sequence": 1,
        "evidence_type": "log",
        "title": "Different content",
        "payload": {},
    }]
    response = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/evidence",
        headers=headers,
        json=conflict,
    )
    assert response.status_code == 409


def test_evidence_rejects_secrets_and_external_artifact_urls(client):
    _, token = _register_runner(client)
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "web",
        "goal": "Reject unsafe evidence",
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    response = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/evidence",
        headers=headers,
        json={
            "lease_token": lease["lease_token"],
            "items": [{
                "sequence": 1,
                "evidence_type": "network",
                "title": "Request",
                "payload": {"headers": {"Authorization": "Bearer secret"}},
                "artifact_ref": "https://evil.example/file",
            }],
        },
    )
    assert response.status_code == 422


def test_user_and_runner_actions_are_audited_with_actor_metadata(client):
    runner, token = _register_runner(client)
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "web",
        "goal": "Audit this run",
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    report = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/report",
        headers=headers,
        json={"lease_token": lease["lease_token"], "status": "passed"},
    )
    assert report.status_code == 200, report.text

    with client.SessionLocal() as db:
        from app import models

        rows = db.query(models.AuditTrail).filter(
            models.AuditTrail.project_id == client.project_id,
            models.AuditTrail.entity_type == models.EntityType.TEST_EXECUTION,
        ).order_by(models.AuditTrail.id).all()
        task_rows = [row for row in rows if row.entity_id == task["id"]]
        assert [row.action.value for row in task_rows] == ["create", "execute"]
        assert task_rows[0].additional_metadata["actor_type"] == "user"
        assert task_rows[1].additional_metadata["actor_type"] == "runner"
        assert task_rows[1].additional_metadata["runner_id"] == runner["id"]
