"""Directory-tree aggregates and move invariants for test cases."""

from conftest import make_http_client


client = make_http_client()


def _create_suite(client, name: str) -> int:
    response = client.post(
        "/test-suites",
        json={"name": name, "project_id": client.project_id},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_section(client, suite_id: int, name: str, parent_id: int | None = None) -> int:
    payload = {"name": name, "test_suite_id": suite_id}
    if parent_id is not None:
        payload["parent_section_id"] = parent_id
    response = client.post("/test-case-sections", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_case(client, suite_id: int, title: str, section_id: int | None = None) -> int:
    payload = {
        "title": title,
        "test_suite_id": suite_id,
        "priority": "medium",
        "test_type": "manual",
    }
    if section_id is not None:
        payload["section_id"] = section_id
    response = client.post("/test-cases", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_directory_hierarchy_returns_direct_descendant_totals_and_paths(client):
    suite_id = _create_suite(client, "Checkout")
    root_id = _create_section(client, suite_id, "Web")
    child_id = _create_section(client, suite_id, "Payment", root_id)
    _create_case(client, suite_id, "Landing", root_id)
    _create_case(client, suite_id, "Card payment", child_id)
    _create_case(client, suite_id, "Wallet payment", child_id)

    response = client.get(f"/projects/{client.project_id}/sections/hierarchy")
    assert response.status_code == 200, response.text
    hierarchy = response.json()["hierarchy"]
    suite = next(item for item in hierarchy if item["test_suite"]["id"] == suite_id)
    root = suite["sections"][0]
    child = root["subsections"][0]

    assert root["direct_case_count"] == 1
    assert root["descendant_case_count"] == 2
    assert root["total_case_count"] == 3
    assert root["full_path"] == "Web"
    assert root["path"] == [{"id": root_id, "name": "Web"}]

    assert child["direct_case_count"] == 2
    assert child["descendant_case_count"] == 0
    assert child["total_case_count"] == 2
    assert child["full_path"] == "Web / Payment"
    assert child["path"] == [
        {"id": root_id, "name": "Web"},
        {"id": child_id, "name": "Payment"},
    ]


def test_bulk_move_rejects_section_from_another_suite(client):
    source_suite_id = _create_suite(client, "Source")
    target_suite_id = _create_suite(client, "Target")
    source_section_id = _create_section(client, source_suite_id, "Original")
    valid_target_id = _create_section(client, source_suite_id, "Moved")
    foreign_target_id = _create_section(client, target_suite_id, "Foreign")
    case_id = _create_case(client, source_suite_id, "Movable", source_section_id)

    rejected = client.patch(
        "/test-cases/bulk",
        json={"ids": [case_id], "section_id": foreign_target_id},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["updated"] == 0
    assert rejected.json()["skipped_ids"] == [case_id]

    accepted = client.patch(
        "/test-cases/bulk",
        json={"ids": [case_id], "section_id": valid_target_id},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["updated"] == 1
    assert accepted.json()["skipped_ids"] == []

    case = client.get(f"/test-cases/{case_id}")
    assert case.status_code == 200, case.text
    assert case.json()["section_id"] == valid_target_id
