"""Execution results keep the case content that was actually run."""

from conftest import make_http_client


client = make_http_client()


def test_result_case_snapshot_is_server_owned_and_immutable(client):
    suite = client.post("/test-suites", json={"name": "Suite", "project_id": client.project_id}).json()
    case = client.post("/test-cases", json={
        "title": "Original title",
        "description": "Original description",
        "preconditions": "Signed in",
        "steps": "Open dashboard",
        "expected_result": "Dashboard opens",
        "test_suite_id": suite["id"],
        "test_type": "manual",
    }).json()
    run = client.post("/test-runs", json={"name": "Run", "project_id": client.project_id}).json()

    created = client.post("/test-results", json={
        "test_run_id": run["id"],
        "test_case_id": case["id"],
        "status": "not_started",
        "test_case_snapshot": {"title": "spoofed"},
    })
    assert created.status_code == 200, created.text
    snapshot = created.json()["test_case_snapshot"]
    assert snapshot["title"] == "Original title"
    assert snapshot["preconditions"] == "Signed in"
    assert snapshot["steps"] == "Open dashboard"

    status_update = client.put(f"/test-results/{created.json()['id']}", json={"status": "pass"})
    assert status_update.status_code == 200, status_update.text
    db = client.SessionLocal()
    try:
        from app import models
        audit = db.query(models.AuditTrail).filter(
            models.AuditTrail.entity_id == created.json()["id"],
            models.AuditTrail.description.like("Test result status changed:%"),
        ).one()
        assert audit.additional_metadata == {"previous_status": "not_started", "status": "pass"}
    finally:
        db.close()

    updated = client.put(f"/test-cases/{case['id']}", json={"title": "Changed later"})
    assert updated.status_code == 200, updated.text
    results = client.get("/test-results", params={"test_run_id": run["id"]})
    assert results.status_code == 200, results.text
    persisted = next(item for item in results.json() if item["id"] == created.json()["id"])
    assert persisted["test_case_snapshot"] == snapshot
    assert persisted["test_case"]["title"] == "Changed later"
