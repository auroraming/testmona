"""Archive runner reports from explicit assertions.

A runner status of ``passed`` is not evidence. The archived status follows
assertion records supplied either as structured result assertions or as
immutable assertion evidence. Tool success alone cannot pass a task.
"""

from __future__ import annotations

from typing import Any


API_RESULT_SCHEMA = "testmona.api_result.v1"


def _assertion_flags(result: dict[str, Any] | None, evidence: list[Any]) -> list[bool]:
    flags: list[bool] = []
    for item in (result or {}).get("assertions") or []:
        if isinstance(item, dict) and isinstance(item.get("passed"), bool):
            flags.append(item["passed"])
    for row in evidence:
        if getattr(row, "evidence_type", None) != "assertion":
            continue
        payload = getattr(row, "payload", None) or {}
        nested = payload.get("assertion") if isinstance(payload, dict) else None
        if isinstance(nested, dict) and isinstance(nested.get("passed"), bool):
            flags.append(nested["passed"])
        elif isinstance(payload, dict) and isinstance(payload.get("passed"), bool):
            flags.append(payload["passed"])
        elif getattr(row, "status", None) in {"passed", "failed"}:
            flags.append(row.status == "passed")
    return flags


def archive_terminal_status(
    reported_status: str,
    result: dict[str, Any] | None,
    evidence: list[Any],
) -> tuple[str, str | None]:
    """Return the status to persist and an archive reason when the report is downgraded."""
    if reported_status != "passed":
        return reported_status, None
    flags = _assertion_flags(result, evidence)
    if not flags:
        return "failed", "missing_assertion"
    if not all(flags):
        return "failed", "assertion_failed"
    return "passed", None


def archived_result(reported_status: str, result: dict[str, Any] | None, reason: str | None) -> dict[str, Any]:
    body = dict(result or {})
    body["runner_reported_status"] = reported_status
    if reason:
        body["archive_reason"] = reason
    return body


def normalize_api_result(source: str, reported: dict[str, Any] | None) -> dict[str, Any]:
    """Canonical API result shared by the native HTTP runner and an API MCP observation."""
    reported = reported or {}
    assertions = []
    for item in reported.get("assertions") or []:
        if not isinstance(item, dict):
            continue
        assertions.append({
            "name": str(item.get("name") or item.get("action") or "assertion"),
            "passed": bool(item.get("passed")),
            "expected": item.get("expected"),
            "actual": item.get("actual"),
        })
    cancelled = bool(reported.get("cancelled"))
    passed = (not cancelled) and bool(assertions) and all(item["passed"] for item in assertions)
    if cancelled:
        error = "Task cancelled"
    elif passed:
        error = None
    else:
        error = reported.get("error") or ("assertion_failed" if assertions else "missing_assertion")
    return {
        "schema": API_RESULT_SCHEMA,
        "source": source,
        "passed": passed,
        "cancelled": cancelled,
        "assertions": assertions,
        "error": error,
        "completed_steps": reported.get("completed_steps"),
    }
