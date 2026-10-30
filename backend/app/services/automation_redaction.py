"""Scrub secret-shaped text before it is stored on automation evidence."""

from __future__ import annotations

import re
from typing import Any


_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_USERINFO = re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@")
_ASSIGNMENT = re.compile(
    r"(?i)\b(token|password|secret|api[_-]?key|access[_-]?token|authorization)\s*[:=]\s*([^\s&,;]{4,})"
)
_DATA_IMAGE = re.compile(r"(?i)data:image/[a-z0-9.+-]+;base64,[a-z0-9+/=]+")
_EMBEDDED_IMAGE_KEYS = {"screenshotbase64", "imagedata", "base64"}
_SECRET_KEY = re.compile(r"(?i)password|secret|token|authorization|api[_-]?key")
_SECRET_VALUE_KEYS = {"value", "text"}


def scrub_sensitive_text(value: str) -> str:
    value = _USERINFO.sub(r"\1", value)
    value = _BEARER.sub("Bearer [redacted]", value)
    value = _ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[redacted]", value)
    value = _DATA_IMAGE.sub("data:image;base64,[redacted]", value)
    return value


def scrub_payload(value: Any) -> Any:
    """Return a copy safe to persist. Embedded screenshot bytes are rejected."""
    if isinstance(value, str):
        return scrub_sensitive_text(value)
    if isinstance(value, list):
        return [scrub_payload(item) for item in value]
    if isinstance(value, dict):
        selector = " ".join(str(value.get(key) or "") for key in ("selector", "element", "name", "target"))
        scrubbed = {}
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in _EMBEDDED_IMAGE_KEYS:
                raise ValueError("evidence cannot embed screenshot bytes; upload an artifact reference")
            if isinstance(child, str) and (
                _SECRET_KEY.search(str(key))
                or (_SECRET_KEY.search(selector) and str(key).lower() in _SECRET_VALUE_KEYS)
            ):
                scrubbed[key] = "[redacted]"
                continue
            scrubbed[key] = scrub_payload(child)
        return scrubbed
    return value
