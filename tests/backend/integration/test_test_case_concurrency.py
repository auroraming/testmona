"""Optimistic concurrency guarantees for test-case editing."""

from conftest import make_http_client


client = make_http_client()


def test_stale_test_case_update_returns_conflict_without_overwrite(client):
    suite = client.post(
        "/test-suites",
        json={"name": "Checkout", "project_id": client.project_id},
    )
    assert suite.status_code == 200, suite.text

    created = client.post(
        "/test-cases",
        json={
            "title": "Original title",
            "test_suite_id": suite.json()["id"],
            "priority": "medium",
            "test_type": "manual",
        },
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    original_updated_at = created.json()["updated_at"]

    first_writer = client.put(
        f"/test-cases/{case_id}",
        json={
            "title": "First writer",
            "expected_updated_at": original_updated_at,
        },
    )
    assert first_writer.status_code == 200, first_writer.text

    stale_writer = client.put(
        f"/test-cases/{case_id}",
        json={
            "title": "Stale writer",
            "expected_updated_at": original_updated_at,
        },
    )
    assert stale_writer.status_code == 409, stale_writer.text
    assert "changed by another user" in stale_writer.json()["detail"]["message"]
    assert stale_writer.json()["detail"]["current_updated_at"] == first_writer.json()["updated_at"]

    current = client.get(f"/test-cases/{case_id}")
    assert current.status_code == 200, current.text
    assert current.json()["title"] == "First writer"
