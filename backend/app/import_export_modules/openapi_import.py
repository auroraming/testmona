"""Safe OpenAPI 3.x preview and test-case conversion endpoints."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Optional

import yaml
from fastapi import Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import crud, rbac, schemas
from ..auth import get_current_active_user
from ..database import get_db
from ..models import TestCase, TestSuite, User
from .base import router


MAX_OPENAPI_BYTES = 2 * 1024 * 1024
MAX_OPERATIONS = 500
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
SENSITIVE_NAMES = {"authorization", "api_key", "apikey", "token", "secret", "password"}


class OpenAPIDraft(BaseModel):
    operation_key: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=255)
    reference: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    preconditions: Optional[str] = None
    priority: str = "medium"
    test_type: str = "manual"
    steps: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class OpenAPICommitRequest(BaseModel):
    project_id: int = Field(gt=0)
    test_suite_id: int = Field(gt=0)
    section_id: Optional[int] = Field(default=None, gt=0)
    duplicate_mode: Literal["skip", "copy"] = "skip"
    drafts: list[OpenAPIDraft] = Field(min_length=1, max_length=1000)


def _contains_remote_ref(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            (key == "$ref" and isinstance(item, str) and item.lower().startswith(("http://", "https://")))
            or _contains_remote_ref(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_remote_ref(item) for item in value)
    return False


def _safe_example(parameter: dict[str, Any]) -> Any:
    name = str(parameter.get("name") or "").lower()
    if any(secret in name for secret in SENSITIVE_NAMES):
        return "<redacted>"
    schema = parameter.get("schema") if isinstance(parameter.get("schema"), dict) else {}
    for source in (parameter, schema):
        if "example" in source:
            return source["example"]
        if "default" in source:
            return source["default"]
        enum = source.get("enum")
        if isinstance(enum, list) and enum:
            return enum[0]
    return f"<{parameter.get('name') or 'value'}>"


def _operation_drafts(path: str, method: str, operation: dict[str, Any], inherited_parameters: list[dict]) -> list[OpenAPIDraft]:
    reference = f"{method.upper()} {path}"
    base_title = operation.get("summary") or operation.get("operationId") or reference
    parameters = [item for item in inherited_parameters + (operation.get("parameters") or []) if isinstance(item, dict)]
    required = [item for item in parameters if item.get("required")]
    responses = operation.get("responses") if isinstance(operation.get("responses"), dict) else {}
    success_codes = [str(code) for code in responses if str(code).startswith("2")]
    expected_code = success_codes[0] if success_codes else "2xx"
    request_values = {str(item.get("name")): _safe_example(item) for item in parameters}
    description = operation.get("description") or operation.get("summary")
    common = {
        "reference": reference,
        "description": description,
        "preconditions": "API base URL is configured. Use non-production credentials and test data.",
        "priority": "medium",
        "test_type": "manual",
    }
    drafts = [OpenAPIDraft(
        operation_key=f"{method.lower()}:{path}:success",
        title=f"{base_title} — success",
        steps=[
            {"step_number": 1, "action": f"Prepare request parameters: {json.dumps(request_values, ensure_ascii=False)}", "expected_result": "Request data satisfies the OpenAPI schema.", "step_type": "action"},
            {"step_number": 2, "action": f"Send {method.upper()} request to {path}.", "expected_result": f"Response status is {expected_code}.", "step_type": "action"},
            {"step_number": 3, "action": "Validate the response body against the declared response schema.", "expected_result": "Response body conforms to the OpenAPI schema.", "step_type": "verification"},
        ],
        **common,
    )]
    for parameter in required[:20]:
        name = str(parameter.get("name") or "required field")
        drafts.append(OpenAPIDraft(
            operation_key=f"{method.lower()}:{path}:missing:{name}",
            title=f"{base_title} — missing required {name}",
            steps=[
                {"step_number": 1, "action": f"Prepare a valid request but omit required {parameter.get('in', 'request')} parameter '{name}'.", "expected_result": "The request is sent without the required value.", "step_type": "action"},
                {"step_number": 2, "action": f"Send {method.upper()} request to {path}.", "expected_result": "The API rejects the request with a declared 4xx response.", "step_type": "verification"},
            ],
            **common,
        ))
    return drafts


def parse_openapi(contents: bytes) -> dict[str, Any]:
    if len(contents) > MAX_OPENAPI_BYTES:
        raise HTTPException(status_code=413, detail="OpenAPI file exceeds the 2 MB limit")
    try:
        text = contents.decode("utf-8-sig")
        document = json.loads(text) if text.lstrip().startswith(("{", "[")) else yaml.safe_load(text)
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid OpenAPI JSON/YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise HTTPException(status_code=400, detail="OpenAPI document must be an object")
    version = str(document.get("openapi") or "")
    if not version.startswith("3."):
        raise HTTPException(status_code=400, detail="MVP supports OpenAPI 3.x documents")
    if _contains_remote_ref(document):
        raise HTTPException(status_code=400, detail="Remote $ref values are not allowed")
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise HTTPException(status_code=400, detail="OpenAPI document has no paths object")

    operations = []
    drafts: list[OpenAPIDraft] = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        inherited = path_item.get("parameters") if isinstance(path_item.get("parameters"), list) else []
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_key = f"{method.lower()}:{path}"
            operations.append({
                "key": operation_key,
                "method": method.upper(),
                "path": path,
                "operation_id": operation.get("operationId"),
                "summary": operation.get("summary"),
                "tags": operation.get("tags") or [],
            })
            drafts.extend(_operation_drafts(path, method, operation, inherited))
            if len(operations) > MAX_OPERATIONS:
                raise HTTPException(status_code=400, detail=f"OpenAPI documents are limited to {MAX_OPERATIONS} operations")
    return {
        "title": ((document.get("info") or {}).get("title") or "OpenAPI import"),
        "version": version,
        "fingerprint": hashlib.sha256(contents).hexdigest(),
        "operations": operations,
        "drafts": [draft.model_dump() for draft in drafts[:1000]],
        "warnings": [] if operations else ["No HTTP operations were found"],
    }


@router.post("/openapi/preview")
async def preview_openapi(
    project_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if not rbac.has_permission(current_user, "write", project_id, db):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    filename = (file.filename or "").lower()
    if not filename.endswith((".json", ".yaml", ".yml")):
        raise HTTPException(status_code=400, detail="OpenAPI file must be JSON or YAML")
    contents = await file.read(MAX_OPENAPI_BYTES + 1)
    return parse_openapi(contents)


@router.post("/openapi/commit")
def commit_openapi_drafts(
    payload: OpenAPICommitRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    suite = db.query(TestSuite).filter(TestSuite.id == payload.test_suite_id).first()
    if suite is None or suite.project_id != payload.project_id:
        raise HTTPException(status_code=400, detail="Test suite must belong to the selected project")
    if not rbac.has_permission(current_user, "write", payload.project_id, db):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if payload.section_id is not None:
        section = crud.get_test_case_section(db, payload.section_id)
        if section is None or section.test_suite_id != suite.id:
            raise HTTPException(status_code=400, detail="Section must belong to the selected test suite")

    created_ids: list[int] = []
    skipped: list[str] = []
    for draft in payload.drafts:
        duplicate = db.query(TestCase).filter(
            TestCase.test_suite_id == suite.id,
            TestCase.reference == draft.reference,
            TestCase.title == draft.title,
            ((TestCase.is_deleted.is_(None)) | (TestCase.is_deleted.is_(False))),
        ).first()
        if duplicate is not None and payload.duplicate_mode == "skip":
            skipped.append(draft.operation_key)
            continue
        title = draft.title if duplicate is None else f"{draft.title} (copy)"
        created = crud.create_test_case(
            db,
            schemas.TestCaseCreate(
                title=title,
                description=draft.description,
                preconditions=draft.preconditions,
                priority=draft.priority,
                test_type=draft.test_type,
                reference=draft.reference,
                test_suite_id=suite.id,
                section_id=payload.section_id,
                is_multistep=True,
                test_steps=[schemas.TestCaseStepCreate(**step) for step in draft.steps],
            ),
            created_by=current_user.id,
        )
        created_ids.append(created.id)
    return {"created_ids": created_ids, "skipped_operation_keys": skipped, "created": len(created_ids), "skipped": len(skipped)}
