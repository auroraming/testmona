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


def test_runner_uploads_and_authorized_user_downloads_referenced_artifact(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_AUTOMATION_ARTIFACT_DIR", str(tmp_path))
    _, token = _register_runner(client)
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id, "runner_type": "web", "goal": "Capture screenshot",
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    upload = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/artifacts",
        headers={**headers, "X-Lease-Token": lease["lease_token"]},
        files={"file": ("screen.png", b"\x89PNG\r\nsmall", "image/png")},
    )
    assert upload.status_code == 200, upload.text
    artifact = upload.json()
    assert artifact["size"] == len(b"\x89PNG\r\nsmall")
    assert artifact["artifact_ref"].startswith(f"ai-automation/{task['id']}/")

    evidence = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/evidence",
        headers=headers,
        json={"lease_token": lease["lease_token"], "items": [{
            "sequence": 1, "evidence_type": "screenshot", "title": "Login page",
            "artifact_ref": artifact["artifact_ref"],
        }]},
    )
    assert evidence.status_code == 200, evidence.text
    artifact_name = artifact["artifact_ref"].rsplit("/", 1)[-1]
    download = client.get(f"/ai-automation/tasks/{task['id']}/artifacts/{artifact_name}")
    assert download.status_code == 200, download.text
    assert download.content == b"\x89PNG\r\nsmall"


def test_artifact_upload_rejects_unsupported_type_and_missing_lease(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_AUTOMATION_ARTIFACT_DIR", str(tmp_path))
    _, token = _register_runner(client)
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id, "runner_type": "web", "goal": "Unsafe artifact",
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    missing = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/artifacts",
        headers=headers, files={"file": ("x.png", b"x", "image/png")},
    )
    assert missing.status_code == 401
    unsupported = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/artifacts",
        headers={**headers, "X-Lease-Token": lease["lease_token"]},
        files={"file": ("x.html", b"<html>", "text/html")},
    )
    assert unsupported.status_code == 415
    missing_file = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/evidence",
        headers=headers,
        json={"lease_token": lease["lease_token"], "items": [{
            "sequence": 1,
            "evidence_type": "screenshot",
            "title": "Missing screenshot",
            "artifact_ref": f"ai-automation/{task['id']}/{'0' * 32}.png",
        }]},
    )
    assert missing_file.status_code == 422
    assert "does not exist" in missing_file.text


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


def test_runner_completion_records_tokens_without_passing(client, monkeypatch):
    from app.services.ai_manager import AICompletionResult

    calls = []

    async def fake_complete(db, request, operation="completion", project_id=None, user_id=None, **_kwargs):
        calls.append({
            "prompt": request.prompt,
            "operation": operation,
            "project_id": project_id,
            "user_id": user_id,
            "max_tokens": request.max_tokens,
        })
        return AICompletionResult(
            provider="fake", model="fake", content='{"type":"tool","tool":"browser_snapshot","arguments":{}}',
            prompt_tokens=3, completion_tokens=4, total_tokens=7,
        )

    monkeypatch.setattr("app.services.ai_manager.generate_ai_completion", fake_complete)
    _runner, token = _register_runner(client, "web")
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "web",
        "execution_mode": "ai",
        "goal": "Check the title",
        "token_budget": 100,
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    response = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/completion",
        headers=headers,
        json={"lease_token": lease["lease_token"], "prompt": "Decide the next browser action", "max_tokens": 800},
    )
    assert response.status_code == 200, response.text
    assert response.json()["prompt_tokens"] == 3
    assert calls[0]["operation"] == "automation_agent"
    assert calls[0]["project_id"] == client.project_id
    stored = client.get(f"/ai-automation/tasks/{task['id']}").json()
    assert stored["status"] == "running"
    assert stored["input_tokens"] == 3
    assert stored["output_tokens"] == 4

    cancelled = client.post(f"/ai-automation/tasks/{task['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    rejected = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/completion",
        headers=headers,
        json={"lease_token": lease["lease_token"], "prompt": "Decide again", "max_tokens": 100},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "AI completion is only available while the task is running"


def test_runner_completion_stops_at_token_budget(client, monkeypatch):
    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("model should not be called after the budget is spent")

    monkeypatch.setattr("app.services.ai_manager.generate_ai_completion", fail_if_called)
    _runner, token = _register_runner(client, "api")
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "api",
        "goal": "Budget",
        "token_budget": 4,
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    from app import models

    with client.SessionLocal() as db:
        row = db.query(models.AIAutomationTask).filter(models.AIAutomationTask.id == task["id"]).one()
        row.input_tokens = 4
        db.commit()
    response = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/completion",
        headers=headers,
        json={"lease_token": lease["lease_token"], "prompt": "Decide", "max_tokens": 50},
    )
    assert response.status_code == 409
    assert "token budget" in response.json()["detail"]
    assert client.get(f"/ai-automation/tasks/{task['id']}").json()["status"] == "running"


def test_expired_lease_cannot_complete_renew_or_pass(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app import models

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("expired lease must not call the model")

    monkeypatch.setattr("app.services.ai_manager.generate_ai_completion", fail_if_called)
    _runner, token = _register_runner(client, "mobile")
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "mobile",
        "goal": "Expired lease",
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    with client.SessionLocal() as db:
        row = db.query(models.AIAutomationTask).filter(models.AIAutomationTask.id == task["id"]).one()
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        db.commit()

    completion = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/completion",
        headers=headers,
        json={"lease_token": lease["lease_token"], "prompt": "Decide", "max_tokens": 50},
    )
    heartbeat = client.post("/internal/ai-automation/heartbeat", headers=headers, json={
        "task_id": task["id"], "lease_token": lease["lease_token"],
    })
    report = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/report",
        headers=headers,
        json={"lease_token": lease["lease_token"], "status": "passed", "result": {"summary": "no"}},
    )
    assert completion.status_code == 409
    assert heartbeat.status_code == 409
    assert report.status_code == 409
    assert "expired" in completion.json()["detail"]
    stored = client.get(f"/ai-automation/tasks/{task['id']}").json()
    assert stored["status"] == "running"
    assert stored["input_tokens"] == 0


def test_invalid_target_origin_is_rejected_when_saved(client):
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "web",
        "goal": "Bad origin",
        "config": {"app_url": "https://example.test/app"},
    })
    assert task.status_code == 422
    assert "origin" in task.text
    environment = client.post("/execution-environments/", json={
        "name": "Unsafe",
        "environment_type": "staging",
        "project_id": client.project_id,
        "config_data": {"base_url": "https://user:pass@example.test"},
    })
    assert environment.status_code == 422
    saved = client.post("/execution-environments/", json={
        "name": "Safe",
        "environment_type": "staging",
        "project_id": client.project_id,
        "config_data": {"app_url": "https://example.test:443"},
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["config_data"]["app_url"] == "https://example.test:443"


def test_ai_report_writes_uploaded_evidence_result_execution_and_run(client, tmp_path, monkeypatch):
    from app import models

    monkeypatch.setenv("AI_AUTOMATION_ARTIFACT_DIR", str(tmp_path))

    with client.SessionLocal() as db:
        suite = models.TestSuite(name="Web", project_id=client.project_id)
        db.add(suite)
        db.flush()
        case = models.TestCase(
            title="Welcome", test_suite_id=suite.id, project_id=client.project_id, priority="medium",
        )
        db.add(case)
        db.flush()
        run = models.TestRun(name="Round 1", project_id=client.project_id, status="pending")
        db.add(run)
        db.flush()
        execution = models.TestExecution(
            test_case_id=case.id, test_run_id=run.id, executor_id=1, status=models.TestStatus.PENDING,
        )
        db.add(execution)
        db.commit()
        case_id, run_id = case.id, run.id

    _runner, token = _register_runner(client, "web")
    task = client.post("/ai-automation/tasks", json={
        "project_id": client.project_id,
        "runner_type": "web",
        "execution_mode": "ai",
        "goal": "Welcome is visible",
        "test_case_id": case_id,
        "test_run_id": run_id,
    }).json()
    headers = {"X-Runner-Token": token}
    lease = client.post("/internal/ai-automation/claim", headers=headers).json()
    uploaded = []
    for name, content, content_type in (
        ("page.png", b"\x89PNG\r\npage", "image/png"),
        ("trace.zip", b"PK\x03\x04trace", "application/zip"),
        ("console.txt", b"console ready", "text/plain"),
    ):
        response = client.post(
            f"/internal/ai-automation/tasks/{task['id']}/artifacts",
            headers={**headers, "X-Lease-Token": lease["lease_token"]},
            files={"file": (name, content, content_type)},
        )
        assert response.status_code == 200, response.text
        uploaded.append(response.json()["artifact_ref"])
    evidence = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/evidence",
        headers=headers,
        json={"lease_token": lease["lease_token"], "items": [{
            "sequence": 1, "evidence_type": "screenshot", "title": "browser_take_screenshot",
            "status": "completed", "payload": {}, "artifact_ref": uploaded[0],
        }, {
            "sequence": 2, "evidence_type": "assertion", "title": "browser_assert_text",
            "status": "passed", "payload": {"output": {"structured_content": {"passed": True}}},
        }, {
            "sequence": 3, "evidence_type": "trace", "title": "Playwright trace",
            "status": "completed", "payload": {}, "artifact_ref": uploaded[1],
        }, {
            "sequence": 4, "evidence_type": "log", "title": "Browser console",
            "status": "completed", "payload": {"text": "console ready"},
            "artifact_ref": uploaded[2],
        }]},
    )
    assert evidence.status_code == 200, evidence.text
    report = client.post(
        f"/internal/ai-automation/tasks/{task['id']}/report",
        headers=headers,
        json={"lease_token": lease["lease_token"], "status": "passed", "result": {"summary": "Title is visible"}},
    )
    assert report.status_code == 200, report.text
    results = client.get("/test-results", params={"test_run_id": run_id})
    assert results.status_code == 200, results.text
    assert results.json()[0]["status"] == "pass"
    assert results.json()[0]["execution_time"] >= 0
    with client.SessionLocal() as db:
        stored_run = db.query(models.TestRun).filter(models.TestRun.id == run_id).one()
        stored_execution = db.query(models.TestExecution).filter(models.TestExecution.test_run_id == run_id).one()
        assert stored_run.status == "completed"
        assert stored_execution.status == models.TestStatus.PASSED
        assert uploaded[0] in stored_execution.screenshots
        assert "Browser console" in stored_execution.logs
