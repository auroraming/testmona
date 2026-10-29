"""Mindmap node/test-case links are project-scoped, idempotent and reversible."""

from conftest import make_http_client


client = make_http_client()


def _suite(client, project_id: int, name: str) -> int:
    response = client.post("/test-suites", json={"name": name, "project_id": project_id})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _case(client, suite_id: int, title: str) -> int:
    response = client.post("/test-cases", json={
        "title": title,
        "test_suite_id": suite_id,
        "priority": "medium",
        "test_type": "manual",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_mindmap_links_are_idempotent_and_reverse_queryable(client):
    suite_id = _suite(client, client.project_id, "Core")
    case_id = _case(client, suite_id, "Login")

    created = client.post("/test-mindmaps/", json={
        "name": "Authentication",
        "project_id": client.project_id,
        "mindmap_data": {
            "version": 1,
            "rootId": "root",
            "nodes": [
                {"id": "root", "title": "Authentication", "parentId": None},
                {"id": "login", "title": "Login", "parentId": "root"},
            ],
        },
    })
    assert created.status_code == 200, created.text
    mindmap_id = created.json()["id"]
    # The server owns authorship; the create payload no longer accepts it.
    assert created.json()["created_by"] > 0

    first = client.post(
        f"/test-mindmaps/{mindmap_id}/nodes/login/test-cases",
        json={"test_case_ids": [case_id, case_id]},
    )
    assert first.status_code == 200, first.text
    assert [item["id"] for item in first.json()] == [case_id]

    repeated = client.post(
        f"/test-mindmaps/{mindmap_id}/nodes/login/test-cases",
        json={"test_case_ids": [case_id]},
    )
    assert repeated.status_code == 200, repeated.text
    assert len(repeated.json()) == 1

    summary = client.get(f"/test-mindmaps/{mindmap_id}/links-summary")
    assert summary.status_code == 200, summary.text
    assert summary.json() == {"login": 1}

    reverse = client.get(f"/test-cases/{case_id}/mindmaps")
    assert reverse.status_code == 200, reverse.text
    assert reverse.json() == [{
        "mindmap_id": mindmap_id,
        "mindmap_name": "Authentication",
        "node_id": "login",
        "node_title": "Login",
    }]

    removed = client.delete(
        f"/test-mindmaps/{mindmap_id}/nodes/login/test-cases/{case_id}"
    )
    assert removed.status_code == 200, removed.text
    assert client.get(f"/test-cases/{case_id}/mindmaps").json() == []
    assert client.get(f"/test-mindmaps/{mindmap_id}/links-summary").json() == {}

def test_mindmap_links_reject_unknown_nodes_and_cross_project_cases(client):
    suite_id = _suite(client, client.project_id, "Core")
    local_case_id = _case(client, suite_id, "Local")
    other_project = client.post("/projects", json={"name": "Other Mindmap Project"})
    assert other_project.status_code == 200, other_project.text
    other_suite_id = _suite(client, other_project.json()["id"], "Foreign")
    foreign_case_id = _case(client, other_suite_id, "Foreign")

    created = client.post("/test-mindmaps/", json={
        "name": "Scoped",
        "project_id": client.project_id,
        "mindmap_data": {"version": 1, "rootId": "root", "nodes": [{"id": "root", "title": "Root"}]},
    })
    mindmap_id = created.json()["id"]

    unknown = client.post(
        f"/test-mindmaps/{mindmap_id}/nodes/missing/test-cases",
        json={"test_case_ids": [local_case_id]},
    )
    assert unknown.status_code == 404

    cross_project = client.post(
        f"/test-mindmaps/{mindmap_id}/nodes/root/test-cases",
        json={"test_case_ids": [foreign_case_id]},
    )
    assert cross_project.status_code == 400


def test_removing_node_cleans_its_links(client):
    suite_id = _suite(client, client.project_id, "Core")
    case_id = _case(client, suite_id, "Login")
    created = client.post("/test-mindmaps/", json={
        "name": "Cleanup",
        "project_id": client.project_id,
        "mindmap_data": {"version": 1, "rootId": "root", "nodes": [
            {"id": "root", "title": "Root"},
            {"id": "child", "title": "Child", "parentId": "root"},
        ]},
    })
    mindmap_id = created.json()["id"]
    linked = client.post(
        f"/test-mindmaps/{mindmap_id}/nodes/child/test-cases",
        json={"test_case_ids": [case_id]},
    )
    assert linked.status_code == 200, linked.text

    updated = client.put(f"/test-mindmaps/{mindmap_id}", json={
        "mindmap_data": {"version": 1, "rootId": "root", "nodes": [
            {"id": "root", "title": "Root"},
        ]},
    })
    assert updated.status_code == 200, updated.text
    assert client.get(f"/test-cases/{case_id}/mindmaps").json() == []


def test_deleted_cases_cannot_be_linked_and_disappear_from_existing_links(client):
    suite_id = _suite(client, client.project_id, "Core")
    linked_case_id = _case(client, suite_id, "Already linked")
    deleted_case_id = _case(client, suite_id, "Deleted before linking")
    created = client.post("/test-mindmaps/", json={
        "name": "Deleted cases",
        "project_id": client.project_id,
        "mindmap_data": {"version": 1, "rootId": "root", "nodes": [{"id": "root", "title": "Root"}]},
    })
    mindmap_id = created.json()["id"]

    linked = client.post(
        f"/test-mindmaps/{mindmap_id}/nodes/root/test-cases",
        json={"test_case_ids": [linked_case_id]},
    )
    assert linked.status_code == 200, linked.text

    assert client.delete(f"/test-cases/{linked_case_id}").status_code == 200
    assert client.get(f"/test-mindmaps/{mindmap_id}/nodes/root/test-cases").json() == []
    assert client.get(f"/test-mindmaps/{mindmap_id}/links-summary").json() == {}

    assert client.delete(f"/test-cases/{deleted_case_id}").status_code == 200
    rejected = client.post(
        f"/test-mindmaps/{mindmap_id}/nodes/root/test-cases",
        json={"test_case_ids": [deleted_case_id]},
    )
    assert rejected.status_code == 400


def test_deactivated_mindmap_disappears_from_reverse_links(client):
    suite_id = _suite(client, client.project_id, "Core")
    case_id = _case(client, suite_id, "Linked case")
    created = client.post("/test-mindmaps/", json={
        "name": "Temporary",
        "project_id": client.project_id,
        "mindmap_data": {"version": 1, "rootId": "root", "nodes": [{"id": "root", "title": "Root"}]},
    })
    mindmap_id = created.json()["id"]
    assert client.post(
        f"/test-mindmaps/{mindmap_id}/nodes/root/test-cases",
        json={"test_case_ids": [case_id]},
    ).status_code == 200

    assert len(client.get(f"/test-cases/{case_id}/mindmaps").json()) == 1
    assert client.delete(f"/test-mindmaps/{mindmap_id}").status_code == 200
    assert client.get(f"/test-cases/{case_id}/mindmaps").json() == []
    assert client.get(f"/test-mindmaps/{mindmap_id}").status_code == 404


def test_project_outsider_cannot_read_or_modify_mindmap_links(client):
    from app import models

    suite_id = _suite(client, client.project_id, "Private")
    case_id = _case(client, suite_id, "Private case")
    created = client.post("/test-mindmaps/", json={
        "name": "Private map",
        "project_id": client.project_id,
        "mindmap_data": {"version": 1, "rootId": "root", "nodes": [{"id": "root", "title": "Root"}]},
    })
    mindmap_id = created.json()["id"]
    assert client.post(
        f"/test-mindmaps/{mindmap_id}/nodes/root/test-cases",
        json={"test_case_ids": [case_id]},
    ).status_code == 200

    with client.SessionLocal() as db:
        outsider = models.User(
            username="mindmap-outsider",
            email="mindmap-outsider@example.com",
            hashed_password="x",
            role="user",
            is_active=True,
            full_name="Mindmap Outsider",
        )
        db.add(outsider)
        db.commit()
        db.refresh(outsider)
        outsider_id = outsider.id

    client.set_current_user(outsider_id)
    assert client.get(f"/test-mindmaps/{mindmap_id}/nodes/root/test-cases").status_code == 403
    assert client.get(f"/test-mindmaps/{mindmap_id}/links-summary").status_code == 403
    assert client.get(f"/test-cases/{case_id}/mindmaps").status_code == 403
    assert client.post(
        f"/test-mindmaps/{mindmap_id}/nodes/root/test-cases",
        json={"test_case_ids": [case_id]},
    ).status_code == 403
    assert client.delete(
        f"/test-mindmaps/{mindmap_id}/nodes/root/test-cases/{case_id}"
    ).status_code == 403
