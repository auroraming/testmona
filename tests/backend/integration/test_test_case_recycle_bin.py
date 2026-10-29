"""Recycle-bin behavior and authorization for soft-deleted test cases."""

from conftest import make_http_client


client = make_http_client()


def _create_suite(client, name: str) -> int:
    response = client.post(
        "/test-suites",
        json={"name": name, "project_id": client.project_id},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_case(client, suite_id: int, title: str) -> int:
    response = client.post(
        "/test-cases",
        json={
            "title": title,
            "test_suite_id": suite_id,
            "priority": "medium",
            "test_type": "manual",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_recycle_bin_filters_by_suite_and_restores_once(client):
    first_suite_id = _create_suite(client, "Checkout")
    second_suite_id = _create_suite(client, "Search")
    first_case_id = _create_case(client, first_suite_id, "Pay by card")
    second_case_id = _create_case(client, second_suite_id, "Find products")

    assert client.delete(f"/test-cases/{first_case_id}").status_code == 200
    assert client.delete(f"/test-cases/{second_case_id}").status_code == 200

    filtered = client.get(
        f"/projects/{client.project_id}/test-cases/recycle-bin",
        params={"test_suite_id": first_suite_id},
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()] == [first_case_id]

    restored = client.post(f"/test-cases/{first_case_id}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["id"] == first_case_id

    remaining = client.get(f"/projects/{client.project_id}/test-cases/recycle-bin")
    assert remaining.status_code == 200, remaining.text
    assert [item["id"] for item in remaining.json()] == [second_case_id]

    repeated = client.post(f"/test-cases/{first_case_id}/restore")
    assert repeated.status_code == 404
    assert repeated.json()["detail"] == "Deleted test case not found"


def test_recycle_bin_and_restore_reject_user_outside_project(client):
    from app import models

    suite_id = _create_suite(client, "Private suite")
    case_id = _create_case(client, suite_id, "Private case")
    assert client.delete(f"/test-cases/{case_id}").status_code == 200

    with client.SessionLocal() as db:
        outsider = models.User(
            username="outsider",
            email="outsider@example.com",
            hashed_password="x",
            role="user",
            is_active=True,
            full_name="Outsider",
        )
        db.add(outsider)
        db.commit()
        db.refresh(outsider)
        outsider_id = outsider.id

    client.set_current_user(outsider_id)

    listed = client.get(f"/projects/{client.project_id}/test-cases/recycle-bin")
    assert listed.status_code == 403

    restored = client.post(f"/test-cases/{case_id}/restore")
    assert restored.status_code == 403

