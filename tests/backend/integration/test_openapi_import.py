"""OpenAPI preview and commit are safe, scoped, and deterministic."""

import json

from conftest import make_http_client


client = make_http_client()


def _suite(client, project_id: int, name: str = "API") -> int:
    response = client.post("/test-suites", json={"name": name, "project_id": project_id})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _section(client, suite_id: int, name: str = "Imported API") -> int:
    response = client.post(
        "/test-case-sections",
        json={"name": name, "test_suite_id": suite_id},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _document() -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Example API", "version": "1.0"},
        "paths": {
            "/users/{userId}": {
                "get": {
                    "summary": "Get user",
                    "parameters": [
                        {"name": "userId", "in": "path", "required": True, "schema": {"type": "string", "example": "42"}},
                        {"name": "authorization", "in": "header", "required": True, "schema": {"type": "string", "example": "secret-value"}},
                    ],
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Missing"}},
                }
            }
        },
    }


def test_preview_generates_success_and_negative_cases_and_redacts_secrets(client):
    response = client.post(
        "/import-export/openapi/preview",
        data={"project_id": str(client.project_id)},
        files={"file": ("openapi.json", json.dumps(_document()), "application/json")},
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["title"] == "Example API"
    assert len(preview["operations"]) == 1
    assert len(preview["drafts"]) == 3
    assert preview["drafts"][0]["reference"] == "GET /users/{userId}"
    assert "secret-value" not in json.dumps(preview)
    assert "<redacted>" in json.dumps(preview)


def test_preview_accepts_yaml_and_rejects_remote_refs(client):
    yaml_body = """openapi: 3.0.3
info: {title: YAML API, version: '1'}
paths:
  /health:
    get:
      responses:
        '200': {description: OK}
"""
    valid = client.post(
        "/import-export/openapi/preview",
        data={"project_id": str(client.project_id)},
        files={"file": ("openapi.yaml", yaml_body, "application/yaml")},
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["title"] == "YAML API"

    document = _document()
    document["components"] = {"schemas": {"User": {"$ref": "https://example.com/user.yaml"}}}
    rejected = client.post(
        "/import-export/openapi/preview",
        data={"project_id": str(client.project_id)},
        files={"file": ("openapi.json", json.dumps(document), "application/json")},
    )
    assert rejected.status_code == 400
    assert "Remote $ref" in rejected.json()["detail"]


def test_commit_creates_steps_and_skips_duplicates(client):
    suite_id = _suite(client, client.project_id)
    preview = client.post(
        "/import-export/openapi/preview",
        data={"project_id": str(client.project_id)},
        files={"file": ("openapi.json", json.dumps(_document()), "application/json")},
    ).json()
    payload = {
        "project_id": client.project_id,
        "test_suite_id": suite_id,
        "duplicate_mode": "skip",
        "drafts": [preview["drafts"][0]],
    }
    first = client.post("/import-export/openapi/commit", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 1

    case_id = first.json()["created_ids"][0]
    case = client.get(f"/test-cases/{case_id}")
    assert case.status_code == 200, case.text
    assert case.json()["is_multistep"] is True
    assert len(case.json()["test_steps"]) == 3

    repeated = client.post("/import-export/openapi/commit", json=payload)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["created"] == 0
    assert repeated.json()["skipped"] == 1


def test_commit_rejects_suite_from_another_project(client):
    other = client.post("/projects", json={"name": "Other"})
    assert other.status_code == 200, other.text
    suite_id = _suite(client, other.json()["id"], "Other API")
    draft = {
        "operation_key": "get:/health:success",
        "title": "Health — success",
        "reference": "GET /health",
        "steps": [{"step_number": 1, "action": "Call API", "expected_result": "200"}],
    }
    response = client.post("/import-export/openapi/commit", json={
        "project_id": client.project_id,
        "test_suite_id": suite_id,
        "drafts": [draft],
    })
    assert response.status_code == 400


def test_commit_targets_section_and_copy_mode_creates_a_distinct_case(client):
    suite_id = _suite(client, client.project_id)
    section_id = _section(client, suite_id)
    draft = {
        "operation_key": "get:/health:success",
        "title": "Health — success",
        "reference": "GET /health",
        "steps": [{"step_number": 1, "action": "Call API", "expected_result": "200"}],
    }
    payload = {
        "project_id": client.project_id,
        "test_suite_id": suite_id,
        "section_id": section_id,
        "duplicate_mode": "copy",
        "drafts": [draft],
    }

    first = client.post("/import-export/openapi/commit", json=payload)
    second = client.post("/import-export/openapi/commit", json=payload)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["created"] == second.json()["created"] == 1
    assert first.json()["created_ids"] != second.json()["created_ids"]

    original = client.get(f"/test-cases/{first.json()['created_ids'][0]}").json()
    copied = client.get(f"/test-cases/{second.json()['created_ids'][0]}").json()
    assert original["section_id"] == copied["section_id"] == section_id
    assert original["title"] == "Health — success"
    assert copied["title"] == "Health — success (copy)"


def test_commit_rejects_section_from_another_suite(client):
    target_suite_id = _suite(client, client.project_id, "Target")
    other_suite_id = _suite(client, client.project_id, "Other")
    other_section_id = _section(client, other_suite_id)
    response = client.post("/import-export/openapi/commit", json={
        "project_id": client.project_id,
        "test_suite_id": target_suite_id,
        "section_id": other_section_id,
        "drafts": [{
            "operation_key": "get:/health:success",
            "title": "Health — success",
            "reference": "GET /health",
            "steps": [{"step_number": 1, "action": "Call API", "expected_result": "200"}],
        }],
    })
    assert response.status_code == 400
    assert "Section must belong" in response.json()["detail"]


def test_openapi_import_rejects_project_outsider(client):
    from app import models

    suite_id = _suite(client, client.project_id)
    with client.SessionLocal() as db:
        outsider = models.User(
            username="openapi-outsider",
            email="openapi-outsider@example.com",
            hashed_password="x",
            role="user",
            is_active=True,
            full_name="OpenAPI Outsider",
        )
        db.add(outsider)
        db.commit()
        db.refresh(outsider)
        outsider_id = outsider.id

    client.set_current_user(outsider_id)
    preview = client.post(
        "/import-export/openapi/preview",
        data={"project_id": str(client.project_id)},
        files={"file": ("openapi.json", json.dumps(_document()), "application/json")},
    )
    assert preview.status_code == 403

    commit = client.post("/import-export/openapi/commit", json={
        "project_id": client.project_id,
        "test_suite_id": suite_id,
        "drafts": [{
            "operation_key": "get:/health:success",
            "title": "Health — success",
            "reference": "GET /health",
            "steps": [{"step_number": 1, "action": "Call API", "expected_result": "200"}],
        }],
    })
    assert commit.status_code == 403
