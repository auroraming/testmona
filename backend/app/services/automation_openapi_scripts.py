"""Turn an OpenAPI or Swagger document into native HTTP Runner steps.

Generated scripts contain paths, methods, and status assertions. Credential
material is a reference name only. Examples that look like secrets are omitted.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException

from ..import_export_modules.openapi_import import parse_openapi


_PATH_PARAM = re.compile(r"\{[^}]+\}")
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def _success_status(responses: dict[str, Any]) -> tuple[int, str | None]:
    codes = [str(code) for code in responses if str(code).startswith("2") and str(code).isdigit()]
    if codes:
        return int(sorted(codes)[0]), None
    return 200, "No numeric 2xx response was declared; the generated assertion expects 200"


def _has_security(document: dict[str, Any], operation: dict[str, Any]) -> bool:
    if operation.get("security"):
        return True
    return bool(document.get("security")) and "security" not in operation


def materialize_api_scripts(document: dict[str, Any], credential_ref: str | None = None) -> dict[str, Any]:
    """Validate the document with the existing safe parser, then emit runner scripts."""
    if not isinstance(document, dict):
        raise HTTPException(status_code=400, detail="OpenAPI document must be an object")
    parse_openapi(json.dumps(document).encode("utf-8"))
    paths = document.get("paths") if isinstance(document.get("paths"), dict) else {}
    scripts = []
    warnings: list[str] = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            responses = operation.get("responses") if isinstance(operation.get("responses"), dict) else {}
            expected, warning = _success_status(responses)
            if warning:
                warnings.append(f"{method.upper()} {path}: {warning}")
            safe_path = _PATH_PARAM.sub("1", str(path))
            step: dict[str, Any] = {
                "action": "request",
                "method": method.upper(),
                "path": safe_path,
                "timeout_ms": 10000,
                "retries": 2,
                "retry_backoff_ms": 250,
            }
            needs_credential = _has_security(document, operation)
            entry: dict[str, Any] = {
                "operation_key": f"{method.lower()}:{path}:success",
                "method": method.upper(),
                "path": safe_path,
                "requires_credential": needs_credential and not credential_ref,
                "credential_refs": [credential_ref] if needs_credential and credential_ref else [],
                "script": [step, {"action": "assert_status", "expected": expected}],
            }
            if needs_credential and credential_ref:
                entry["auth"] = {"type": "bearer", "credential_ref": credential_ref}
            elif needs_credential:
                warnings.append(f"{method.upper()} {path}: security is declared, but no credential reference was provided")
            scripts.append(entry)
            if len(scripts) >= 100:
                warnings.append("Script generation stopped at 100 operations")
                return {"scripts": scripts, "warnings": warnings}
    return {"scripts": scripts, "warnings": warnings}
