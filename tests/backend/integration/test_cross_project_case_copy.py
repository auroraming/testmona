"""Cross-project copying is previewed, idempotent, and excludes history."""

from conftest import make_http_client


client = make_http_client()


def test_cross_project_copy_creates_new_cases_without_history(client):
    from app import models

    source_suite = client.post("/test-suites", json={"name": "Source", "project_id": client.project_id}).json()
    source = client.post("/test-cases", json={
        "title": "Checkout", "description": "Source content", "test_suite_id": source_suite["id"],
        "test_type": "manual", "priority": "high", "test_steps": [{
            "step_number": 1, "action": "Pay", "expected_result": "Paid", "step_type": "manual",
        }],
    }).json()
    db = client.SessionLocal()
    try:
        owner_id = db.query(models.Project.owner_id).filter(models.Project.id == client.project_id).scalar()
        target_project = models.Project(name="Target", owner_id=owner_id)
        db.add(target_project)
        db.commit()
        db.refresh(target_project)
        target_project_id = target_project.id
    finally:
        db.close()
    target_suite = client.post("/test-suites", json={"name": "Target suite", "project_id": target_project_id}).json()
    target_section = client.post("/test-case-sections", json={"name": "Payments", "test_suite_id": target_suite["id"]}).json()
    payload = {
        "test_case_ids": [source["id"]], "target_test_suite_id": target_suite["id"],
        "target_section_id": target_section["id"],
    }

    preview = client.post("/test-cases/cross-project-copy/preview", json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_copy"] is True
    assert preview.json()["cases"][0]["step_count"] == 1

    missing_key = client.post("/test-cases/cross-project-copy/commit", json=payload)
    assert missing_key.status_code == 400

    first = client.post("/test-cases/cross-project-copy/commit", json=payload, headers={"Idempotency-Key": "copy-checkout-001"})
    assert first.status_code == 200, first.text
    copied_id = first.json()["cases"][0]["test_case_id"]
    assert copied_id != source["id"]
    repeated = client.post("/test-cases/cross-project-copy/commit", json=payload, headers={"Idempotency-Key": "copy-checkout-001"})
    assert repeated.status_code == 200
    assert repeated.json() == first.json()

    copied = client.get(f"/test-cases/{copied_id}")
    assert copied.status_code == 200, copied.text
    assert copied.json()["test_suite_id"] == target_suite["id"]
    assert copied.json()["section_id"] == target_section["id"]
    assert copied.json()["title"] == "Checkout"
    assert client.get(f"/test-cases/{copied_id}/steps").json()[0]["action"] == "Pay"
    assert client.get(f"/test-cases/{copied_id}/revisions").json() == []
    assert client.get(f"/test-cases/{copied_id}/execution-history").json() == []
    assert len(client.get("/test-cases", params={"test_suite_id": target_suite["id"]}).json()) == 1


def test_cross_project_copy_rejects_same_project(client):
    source_suite = client.post("/test-suites", json={"name": "Source", "project_id": client.project_id}).json()
    target_suite = client.post("/test-suites", json={"name": "Target", "project_id": client.project_id}).json()
    source = client.post("/test-cases", json={
        "title": "Case", "test_suite_id": source_suite["id"], "test_type": "manual",
    }).json()
    payload = {"test_case_ids": [source["id"]], "target_test_suite_id": target_suite["id"]}
    assert client.post("/test-cases/cross-project-copy/preview", json=payload).status_code == 400
