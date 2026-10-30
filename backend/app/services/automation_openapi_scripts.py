"""Turn an OpenAPI or Swagger document into native HTTP Runner steps.

Generated scripts contain paths, methods, and status assertions. Credential
material is a reference name only. Examples that look like secrets are omitted.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import HTTPException

from ..import_export_modules.openapi_import import parse_openapi


_PATH_PARAM = re.compile(r"\{[^}]+\}")
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
_SCHEMA_KEYS = {
    "type", "nullable", "enum", "required", "properties", "items",
    "additionalProperties", "allOf", "anyOf", "oneOf",
}
_MAX_SCHEMA_NODES = 500
_MAX_SCHEMA_DEPTH = 20
_SENSITIVE_NAMES = {"authorization", "api_key", "apikey", "token", "secret", "password"}


def _success_status(responses: dict[str, Any]) -> tuple[int, str | None]:
    codes = [str(code) for code in responses if str(code).startswith("2") and str(code).isdigit()]
    if codes:
        return int(sorted(codes)[0]), None
    return 200, "No numeric 2xx response was declared; the generated assertion expects 200"


def _has_security(document: dict[str, Any], operation: dict[str, Any]) -> bool:
    if operation.get("security"):
        return True
    return bool(document.get("security")) and "security" not in operation


def _response_schema(response: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(response.get("schema"), dict):  # Swagger 2.0
        return response["schema"]
    content = response.get("content")
    if not isinstance(content, dict):
        return None
    for media_type, media in content.items():
        if (media_type == "application/json" or str(media_type).endswith("+json")) and isinstance(media, dict):
            schema = media.get("schema")
            if isinstance(schema, dict):
                return schema
    return None


def _local_ref(document: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError("Only local response schema references are supported")
    current: Any = document
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"Unresolved response schema reference: {ref}")
        current = current[part]
    if not isinstance(current, dict):
        raise ValueError(f"Response schema reference is not an object: {ref}")
    return current


def _materialize_schema(
    document: dict[str, Any], schema: dict[str, Any], *, depth: int = 0,
    budget: list[int] | None = None, refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Copy the safe validation subset and resolve local refs for the remote Runner."""
    if budget is None:
        budget = [0]
    budget[0] += 1
    if budget[0] > _MAX_SCHEMA_NODES or depth > _MAX_SCHEMA_DEPTH:
        raise ValueError("Response schema exceeds validation limits")
    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or ref in refs:
            raise ValueError("Response schema contains an invalid or recursive reference")
        return _materialize_schema(document, _local_ref(document, ref), depth=depth + 1, budget=budget, refs=(*refs, ref))
    result: dict[str, Any] = {}
    for key in _SCHEMA_KEYS:
        value = schema.get(key)
        if key == "properties" and isinstance(value, dict):
            result[key] = {
                str(name): _materialize_schema(document, child, depth=depth + 1, budget=budget, refs=refs)
                for name, child in value.items() if isinstance(child, dict)
            }
        elif key == "items" and isinstance(value, dict):
            result[key] = _materialize_schema(document, value, depth=depth + 1, budget=budget, refs=refs)
        elif key in {"allOf", "anyOf", "oneOf"} and isinstance(value, list):
            result[key] = [
                _materialize_schema(document, child, depth=depth + 1, budget=budget, refs=refs)
                for child in value if isinstance(child, dict)
            ]
        elif key in {"type", "nullable", "enum", "required", "additionalProperties"} and value is not None:
            result[key] = value
    return result


def _sample_value(document: dict[str, Any], schema: dict[str, Any], name: str = "", depth: int = 0) -> Any:
    if depth > 8 or any(part in name.lower() for part in _SENSITIVE_NAMES):
        return None
    if isinstance(schema.get("$ref"), str):
        return _sample_value(document, _local_ref(document, schema["$ref"]), name, depth + 1)
    for key in ("example", "default"):
        if key in schema:
            return schema[key]
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]
    schema_type = schema.get("type")
    if schema_type == "object" or isinstance(schema.get("properties"), dict):
        required = set(schema.get("required") or [])
        return {
            key: value
            for key, child in (schema.get("properties") or {}).items()
            if key in required and isinstance(child, dict)
            and (value := _sample_value(document, child, key, depth + 1)) is not None
        }
    if schema_type == "array" and isinstance(schema.get("items"), dict):
        value = _sample_value(document, schema["items"], name, depth + 1)
        return [] if value is None else [value]
    return {"integer": 1, "number": 1, "boolean": True, "string": "test"}.get(schema_type, "test")


def _request_data(
    document: dict[str, Any], path: str, path_item: dict[str, Any], operation: dict[str, Any], warnings: list[str],
) -> tuple[str, Any | None]:
    inherited = path_item.get("parameters") if isinstance(path_item.get("parameters"), list) else []
    own = operation.get("parameters") if isinstance(operation.get("parameters"), list) else []
    parameters = [
        item for item in (*inherited, *own)
        if isinstance(item, dict)
    ]
    resolved_path = path
    query: dict[str, Any] = {}
    body = None
    for parameter in parameters:
        if isinstance(parameter.get("$ref"), str):
            parameter = _local_ref(document, parameter["$ref"])
        name = str(parameter.get("name") or "")
        location = parameter.get("in")
        if not name or not parameter.get("required") or location not in {"path", "query", "body"}:
            continue
        schema = parameter.get("schema") if isinstance(parameter.get("schema"), dict) else parameter
        value = _sample_value(document, schema, name)
        if value is None:
            warnings.append(f"Required {location} parameter {name} was omitted because it may contain a credential")
        elif location == "path":
            resolved_path = resolved_path.replace("{" + name + "}", quote(str(value), safe=""))
        elif location == "query":
            query[name] = value
        else:  # Swagger 2.0 body parameter
            body = value
    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        if isinstance(request_body.get("$ref"), str):
            request_body = _local_ref(document, request_body["$ref"])
        media = (request_body.get("content") or {}).get("application/json")
        if isinstance(media, dict) and isinstance(media.get("schema"), dict):
            body = _sample_value(document, media["schema"])
    resolved_path = _PATH_PARAM.sub("1", resolved_path)
    if query:
        resolved_path += ("&" if "?" in resolved_path else "?") + urlencode(query, doseq=True)
    return resolved_path, body


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
            response = responses.get(str(expected)) if isinstance(responses.get(str(expected)), dict) else None
            safe_path, request_body = _request_data(document, str(path), path_item, operation, warnings)
            step: dict[str, Any] = {
                "action": "request",
                "method": method.upper(),
                "path": safe_path,
                "timeout_ms": 10000,
                "retries": 2,
                "retry_backoff_ms": 250,
            }
            if request_body is not None:
                step["body"] = request_body
            needs_credential = _has_security(document, operation)
            script = [step, {"action": "assert_status", "expected": expected}]
            schema = _response_schema(response) if response else None
            if schema:
                try:
                    script.append({"action": "assert_json_schema", "schema": _materialize_schema(document, schema)})
                except ValueError as exc:
                    warnings.append(f"{method.upper()} {path}: response schema assertion skipped: {exc}")
            entry: dict[str, Any] = {
                "operation_key": f"{method.lower()}:{path}:success",
                "method": method.upper(),
                "path": safe_path,
                "requires_credential": needs_credential and not credential_ref,
                "credential_refs": [credential_ref] if needs_credential and credential_ref else [],
                "script": script,
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
