"""Deterministic failure suggestions from stored evidence.

A suggestion is not a defect. Confirming or dismissing it only records a human
decision and never creates or links a defect.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .automation_redaction import scrub_payload, scrub_sensitive_text


_CATEGORY_ORDER = (
    "timeout",
    "authorization_rejected",
    "upstream_error",
    "assertion_mismatch",
    "missing_assertion",
    "resource_missing",
    "blocked_precondition",
    "unclassified_failure",
)
_SUMMARIES = {
    "timeout": "The run stopped because a timeout was recorded. Review the listed evidence before deciding what to change.",
    "authorization_rejected": "A request was rejected with an authentication or authorization status. Confirm the credential reference and target account; no secret is included here.",
    "upstream_error": "A recorded request returned a server error status. The suggestion cites the status and redacted URL only.",
    "assertion_mismatch": "An explicit assertion did not match the observed value. Compare the redacted expected and actual values.",
    "missing_assertion": "The run had no passing explicit assertion, so it cannot be treated as passed.",
    "resource_missing": "A recorded request returned 404. Check the path and environment base URL.",
    "blocked_precondition": "The runner reported that a required precondition was unavailable. This suggestion does not invent a device session.",
    "unclassified_failure": "The run failed without a more specific evidence pattern. Review the cited evidence manually.",
}


def _assertion_passed(payload: dict[str, Any], status: str | None) -> bool | None:
    nested = payload.get("assertion")
    if isinstance(nested, dict) and isinstance(nested.get("passed"), bool):
        return nested["passed"]
    if isinstance(payload.get("passed"), bool):
        return payload["passed"]
    if status in {"passed", "failed"}:
        return status == "passed"
    return None


def _clip(value: Any) -> Any:
    if isinstance(value, str):
        return value[:200]
    return value


def build_failure_suggestion(status: str, error_message: str | None, evidence: list[Any]) -> dict[str, Any] | None:
    """Return a suggestion body, or None when the terminal status is not a failure."""
    if status not in {"failed", "timed_out", "blocked"}:
        return None
    categories: list[str] = []
    signals: list[dict[str, Any]] = []
    if status == "timed_out":
        categories.append("timeout")
    if status == "blocked":
        categories.append("blocked_precondition")
    scrubbed_error = scrub_sensitive_text(error_message or "")
    if "missing_assertion" in scrubbed_error:
        categories.append("missing_assertion")
    if "timeout" in scrubbed_error.lower():
        categories.append("timeout")

    for item in evidence:
        payload = scrub_payload(getattr(item, "payload", None) or {})
        if not isinstance(payload, dict):
            payload = {}
        evidence_type = getattr(item, "evidence_type", "")
        sequence = getattr(item, "sequence", None)
        item_status = getattr(item, "status", None)
        if evidence_type == "assertion" and _assertion_passed(payload, item_status) is False:
            categories.append("assertion_mismatch")
            nested = payload.get("assertion") if isinstance(payload.get("assertion"), dict) else payload
            signals.append({
                "sequence": sequence,
                "evidence_type": "assertion",
                "expected": _clip(nested.get("expected")),
                "actual": _clip(nested.get("actual")),
            })
        elif evidence_type == "network":
            code = payload.get("status", payload.get("status_code"))
            signal = {
                "sequence": sequence,
                "evidence_type": "network",
                "method": payload.get("method"),
                "url": _clip(payload.get("url") or payload.get("path")),
                "status": code,
            }
            signals.append(signal)
            if code in {401, 403}:
                categories.append("authorization_rejected")
            elif isinstance(code, int) and code >= 500:
                categories.append("upstream_error")
            elif code == 404:
                categories.append("resource_missing")
        elif evidence_type == "screenshot" and getattr(item, "artifact_ref", None):
            signals.append({
                "sequence": sequence,
                "evidence_type": "screenshot",
                "artifact_ref": getattr(item, "artifact_ref", None),
            })
        elif evidence_type == "log":
            text = scrub_sensitive_text(json.dumps(payload, ensure_ascii=False))
            if "timeout" in text.lower():
                categories.append("timeout")
            signals.append({"sequence": sequence, "evidence_type": "log", "excerpt": text[:200]})

    if not categories:
        categories.append("unclassified_failure")
    category = next(name for name in _CATEGORY_ORDER if name in categories)
    body = {
        "category": category,
        "summary": _SUMMARIES[category] + " Confirming this suggestion does not create or link a defect.",
        "signals": signals[:20],
    }
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    body["content_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return body
