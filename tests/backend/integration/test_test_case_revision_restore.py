"""Revision restore is append-only and protected from stale clients."""

from conftest import make_http_client


client = make_http_client()


def test_restore_revision_creates_new_revision_and_rejects_stale_token(client):
    suite = client.post("/test-suites", json={"name": "Suite", "project_id": client.project_id}).json()
    created = client.post("/test-cases", json={
        "title": "First", "test_suite_id": suite["id"], "test_type": "manual",
    }).json()
    changed = client.put(f"/test-cases/{created['id']}", json={
        "title": "Second", "expected_updated_at": created["updated_at"],
    })
    assert changed.status_code == 200, changed.text

    revisions = client.get(f"/test-cases/{created['id']}/revisions").json()
    first = min(revisions, key=lambda revision: revision["revision_number"])
    restored = client.post(
        f"/test-cases/{created['id']}/revisions/{first['revision_number']}/restore",
        json={"expected_updated_at": changed.json()["updated_at"]},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["title"] == "First"

    after = client.get(f"/test-cases/{created['id']}/revisions").json()
    assert max(revision["revision_number"] for revision in after) > max(revision["revision_number"] for revision in revisions)
    assert any((revision.get("change_reason") or "").startswith("Restored revision") for revision in after)

    stale = client.post(
        f"/test-cases/{created['id']}/revisions/{first['revision_number']}/restore",
        json={"expected_updated_at": changed.json()["updated_at"]},
    )
    assert stale.status_code == 409
