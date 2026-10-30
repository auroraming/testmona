"""Convert reviewed exploration evidence into a fixed-script draft.

The draft is data for a person to approve. It is not queued or executed here.
Secret-shaped argument values are replaced with a credential placeholder.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


_SECRET_KEY = re.compile(r"(?i)password|secret|token|authorization|api[_-]?key")
_PLACEHOLDER = "${cred:replace-me}"


def _redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.scheme or not parts.hostname:
        return value
    hostname = parts.hostname
    netloc = hostname + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _looks_like_secret(value: str) -> bool:
    if " " in value:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._~+/=-]{20,}", value))


def _clean_value(key: str, value: Any, warnings: list[str]) -> Any:
    if isinstance(value, str) and (_SECRET_KEY.search(key) or _looks_like_secret(value)):
        warnings.append(f"{key} was replaced with a credential placeholder")
        return _PLACEHOLDER
    if isinstance(value, str) and len(value) > 200:
        warnings.append(f"{key} was truncated")
        return value[:200]
    return value


def _step_from_mapping(action: str, arguments: dict[str, Any], warnings: list[str]) -> dict[str, Any] | None:
    normalized = action.strip().lower()
    if normalized in {"navigate", "browser_navigate"}:
        url = arguments.get("url")
        if not isinstance(url, str) or not url:
            return None
        return {"action": "navigate", "url": _redact_url(_clean_value("url", url, warnings))}
    if normalized in {"click", "browser_click"}:
        selector = arguments.get("selector") or arguments.get("element") or arguments.get("target")
        if not isinstance(selector, str) or not selector:
            return None
        return {"action": "click", "selector": _clean_value("selector", selector, warnings)}
    if normalized in {"fill", "type", "browser_type", "browser_fill_form"}:
        selector = arguments.get("selector") or arguments.get("element")
        if not isinstance(selector, str) or not selector:
            return None
        raw_value = arguments.get("value", arguments.get("text", ""))
        return {
            "action": "fill",
            "selector": _clean_value("selector", selector, warnings),
            "value": _clean_value("value", raw_value, warnings),
        }
    if normalized in {"assert_text", "browser_assert_text"}:
        selector = arguments.get("selector") or "page"
        expected = arguments.get("expected")
        if expected is None:
            return None
        return {
            "action": "assert_text",
            "selector": str(selector),
            "expected": _clean_value("expected", expected, warnings),
        }
    if normalized in {"assert_visible", "browser_assert_visible"}:
        selector = arguments.get("selector") or arguments.get("name")
        if not isinstance(selector, str) or not selector:
            return None
        return {"action": "assert_visible", "selector": selector}
    if normalized == "request":
        path = arguments.get("path")
        if not isinstance(path, str) or not path or "://" in path:
            return None
        step: dict[str, Any] = {
            "action": "request",
            "method": str(arguments.get("method") or "GET").upper(),
            "path": path.split("?", 1)[0],
        }
        if arguments.get("timeout_ms") is not None:
            step["timeout_ms"] = arguments.get("timeout_ms")
        return step
    if normalized == "assert_status" and arguments.get("expected") is not None:
        return {"action": "assert_status", "expected": arguments.get("expected")}
    if normalized == "assert_json_path" and arguments.get("path") and "expected" in arguments:
        return {"action": "assert_json_path", "path": arguments.get("path"), "expected": arguments.get("expected")}
    return None


def fixed_script_from_evidence(*, execution_mode: str, config: dict[str, Any] | None, evidence: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Build a draft script from a saved script or from step evidence."""
    warnings: list[str] = []
    config = config or {}
    saved = config.get("script") if isinstance(config, dict) else None
    if execution_mode == "script" and isinstance(saved, list) and saved:
        steps = []
        for item in saved:
            if not isinstance(item, dict) or not item.get("action"):
                continue
            converted = _step_from_mapping(str(item["action"]), item, warnings)
            if converted:
                steps.append(converted)
        if not steps:
            raise ValueError("The saved script has no convertible steps")
        return steps, warnings

    steps = []
    for item in evidence:
        if getattr(item, "evidence_type", None) not in {"step", "assertion", "network"}:
            continue
        payload = getattr(item, "payload", None) or {}
        if not isinstance(payload, dict):
            continue
        action = payload.get("action") or payload.get("tool")
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else payload
        if not isinstance(action, str):
            continue
        converted = _step_from_mapping(action, arguments, warnings)
        if converted:
            steps.append(converted)
    if not steps:
        raise ValueError("No exploration evidence could be converted into a fixed script")
    if not any(str(step.get("action", "")).startswith("assert_") for step in steps):
        warnings.append("The draft has no explicit assertion yet. Approval still does not execute it, and a run cannot pass until an assertion is added.")
    return steps, warnings
