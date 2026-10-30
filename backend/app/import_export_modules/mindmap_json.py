"""Versioned JSON round-trip for the test-case mind-map workspace."""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import auth, crud
from ..database import get_db
from ..models import TestCase, TestCaseSection, User
from ..services.import_export_utils import (
    DataValidationError,
    MAX_ROWS_PER_IMPORT,
    MAX_STEPS_PER_TEST_CASE,
    normalize_priority,
    normalize_test_type,
)
from .base import router
from .helpers import (
    acquire_import_lock,
    begin_idempotent_request,
    complete_idempotent_request,
    create_import_test_case_without_commit,
    ensure_import_permission,
    fail_idempotent_request,
    get_idempotency_key,
    get_test_suite_or_404,
    make_imported_copy_title,
    parse_multistep_data,
    release_import_lock,
)


class MindmapJsonImportRequest(BaseModel):
    test_suite_id: int = Field(gt=0)
    document: dict[str, Any]
    duplicate_mode: Literal["skip", "copy"] = "skip"
    dry_run: bool = True


def _parse_document(document: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if document.get("format") != "testmona.test-case-mindmap" or document.get("version") != 1:
        raise HTTPException(status_code=400, detail="Unsupported TestMona mind-map JSON format or version")
    raw_sections = document.get("sections")
    raw_cases = document.get("test_cases")
    if not isinstance(raw_sections, list) or not isinstance(raw_cases, list):
        raise HTTPException(status_code=400, detail="Mind-map JSON requires sections and test_cases arrays")
    if len(raw_cases) > MAX_ROWS_PER_IMPORT:
        raise HTTPException(status_code=400, detail=f"JSON imports are limited to {MAX_ROWS_PER_IMPORT} test cases")

    sections: list[dict[str, Any]] = []
    section_ids: set[int] = set()

    def visit(items: list[Any], parent_source_id: int | None, path: tuple[str, ...], depth: int) -> None:
        if depth > 20:
            raise HTTPException(status_code=400, detail="Section nesting exceeds 20 levels")
        for item in items:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail="Each section must be an object")
            try:
                source_id = int(item.get("id"))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="Each section requires a numeric id") from exc
            name = str(item.get("name") or "").strip()
            if source_id in section_ids or not name or len(name) > 255:
                raise HTTPException(status_code=400, detail="Section ids must be unique and names must be 1-255 characters")
            section_ids.add(source_id)
            section_path = (*path, name.casefold())
            sections.append({"source_id": source_id, "parent_source_id": parent_source_id, "name": name, "path": section_path})
            children = item.get("children") or []
            if not isinstance(children, list):
                raise HTTPException(status_code=400, detail=f"Section '{name}' children must be an array")
            visit(children, source_id, section_path, depth + 1)

    visit(raw_sections, None, (), 1)
    if len(sections) > 5000:
        raise HTTPException(status_code=400, detail="JSON imports are limited to 5000 sections")

    cases: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, item in enumerate(raw_cases, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"Test case {index} must be an object")
        title = str(item.get("title") or "").strip()
        if not title or len(title) > 255:
            raise HTTPException(status_code=400, detail=f"Test case {index} title must be 1-255 characters")
        steps = item.get("steps") or []
        if not isinstance(steps, list) or len(steps) > MAX_STEPS_PER_TEST_CASE:
            raise HTTPException(status_code=400, detail=f"Test case '{title}' has invalid or too many steps")
        if item.get("is_multistep"):
            try:
                parse_multistep_data(json.dumps(steps), title)
            except DataValidationError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        section_id = item.get("section_id")
        if section_id is not None:
            try:
                section_id = int(section_id)
            except (TypeError, ValueError):
                section_id = None
            if section_id not in section_ids:
                warnings.append(f"{title}: source section was not found; case will be imported at suite root")
                section_id = None
        cases.append({
            **item,
            "title": title,
            "section_id": section_id,
            "steps": steps,
            "priority": normalize_priority(str(item.get("priority") or "medium")),
            "test_type": normalize_test_type(str(item.get("test_type") or "manual")),
        })
    return sections, cases, warnings


def _existing_section_paths(db: Session, suite_id: int) -> dict[tuple[str, ...], TestCaseSection]:
    rows = db.query(TestCaseSection).filter(
        TestCaseSection.test_suite_id == suite_id,
        TestCaseSection.is_active.is_(True),
    ).all()
    by_id = {row.id: row for row in rows}
    cache: dict[int, tuple[str, ...]] = {}

    def path(row: TestCaseSection) -> tuple[str, ...]:
        if row.id in cache:
            return cache[row.id]
        parent = by_id.get(row.parent_section_id)
        value = (*path(parent), row.name.casefold()) if parent else (row.name.casefold(),)
        cache[row.id] = value
        return value

    return {path(row): row for row in rows}


@router.post("/import/test-cases/mindmap-json")
def import_test_case_mindmap_json(
    payload: MindmapJsonImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    suite = get_test_suite_or_404(db, payload.test_suite_id)
    ensure_import_permission(current_user, suite.project_id, db)
    sections, cases, warnings = _parse_document(payload.document)
    existing_paths = _existing_section_paths(db, suite.id)
    existing_titles = {
        title.casefold() for (title,) in db.query(TestCase.title).filter(
            TestCase.test_suite_id == suite.id,
            TestCase.is_deleted.is_(False),
        ).all()
    }
    preview_titles = set(existing_titles)
    duplicate_count = 0
    for case in cases:
        normalized_title = case["title"].casefold()
        if normalized_title in preview_titles:
            duplicate_count += 1
        preview_titles.add(normalized_title)
    preview = {
        "dry_run": payload.dry_run,
        "section_count": len(sections),
        "new_section_count": sum(section["path"] not in existing_paths for section in sections),
        "test_case_count": len(cases),
        "duplicate_count": duplicate_count,
        "would_create_count": len(cases) - duplicate_count if payload.duplicate_mode == "skip" else len(cases),
        "warnings": warnings,
        "created_ids": [],
    }
    if payload.dry_run:
        return preview

    record_key = get_idempotency_key(request, current_user.id, "mindmap-json-import")
    cached = begin_idempotent_request(db, record_key, current_user.id, "mindmap-json-import")
    if cached is not None:
        return cached
    lock_owner = record_key or f"mindmap-json:{uuid.uuid4()}"
    lock_key = f"test-suite-import:{suite.id}"
    try:
        acquire_import_lock(
            db=db, lock_key=lock_key, owner=lock_owner, user_id=current_user.id,
            operation="mindmap-json-import", project_id=suite.project_id,
            test_suite_id=suite.id, filename="mindmap.json",
        )
        crud.ensure_default_priority_and_test_type_definitions(db, suite.project_id, current_user.id)
        source_to_actual: dict[int, int] = {}
        for section in sections:
            existing = existing_paths.get(section["path"])
            if existing:
                source_to_actual[section["source_id"]] = existing.id
                continue
            row = TestCaseSection(
                name=section["name"], test_suite_id=suite.id,
                parent_section_id=source_to_actual.get(section["parent_source_id"]),
            )
            db.add(row)
            db.flush()
            source_to_actual[section["source_id"]] = row.id
            existing_paths[section["path"]] = row

        created_ids: list[int] = []
        used_titles = set(existing_titles)
        skipped_count = 0
        for case in cases:
            title = case["title"]
            if title.casefold() in used_titles:
                if payload.duplicate_mode == "skip":
                    skipped_count += 1
                    continue
                title = make_imported_copy_title(title, used_titles)
            is_multistep = bool(case.get("is_multistep"))
            steps = parse_multistep_data(json.dumps(case["steps"]), title) if is_multistep else []
            first_step = case["steps"][0] if case["steps"] else {}
            row = create_import_test_case_without_commit(db, {
                "title": title,
                "description": str(case.get("description") or ""),
                "preconditions": str(case.get("preconditions") or ""),
                "steps": "" if is_multistep else str(first_step.get("action") or ""),
                "expected_result": "" if is_multistep else str(first_step.get("expected_result") or ""),
                "priority": str(case.get("priority") or "medium"),
                "status": "active",
                "test_type": str(case.get("test_type") or "manual"),
                "test_suite_id": suite.id,
                "project_id": suite.project_id,
                "section_id": source_to_actual.get(case["section_id"]),
                "is_multistep": is_multistep,
                "test_steps": steps,
            }, current_user.id)
            created_ids.append(row.id)
            used_titles.add(title.casefold())
        db.commit()
        response = {
            **preview,
            "dry_run": False,
            "created_ids": created_ids,
            "created_count": len(created_ids),
            "skipped_count": skipped_count,
        }
        complete_idempotent_request(db, record_key, response)
        release_import_lock(db, lock_key, lock_owner)
        return response
    except HTTPException as exc:
        db.rollback()
        fail_idempotent_request(db, record_key, str(exc.detail))
        release_import_lock(db, lock_key, lock_owner)
        raise
    except Exception as exc:
        db.rollback()
        fail_idempotent_request(db, record_key, str(exc))
        release_import_lock(db, lock_key, lock_owner)
        raise HTTPException(status_code=400, detail=f"Mind-map JSON import failed: {exc}") from exc
