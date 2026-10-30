"""Default-deny policy for automation targets.

Production environment types, payment-like hosts, and destructive operations are
rejected. An explicit allowlist can narrow the remaining non-production targets.
There is no switch that turns production or real-money paths back on.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException


PRODUCTION_ENVIRONMENT_TYPES = {"production", "prod", "live"}
DESTRUCTIVE_PATH_MARKERS = ("/payments", "/payment", "/charge", "/charges", "/transfer", "/payout", "/refund", "/wallet")
DESTRUCTIVE_METHODS = {"DELETE"}
_ACCOUNT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,79}$")
_CREDENTIAL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,78}$")


def _origin(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="Allowlist origins must be http(s) origins without credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise HTTPException(status_code=422, detail="Allowlist origins cannot include a path, query, or fragment")
    return f"{parsed.scheme}://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")


def _host_denied(hostname: str) -> str | None:
    labels = set(hostname.lower().rstrip(".").split("."))
    if labels & {"payments", "payment", "billing", "checkout", "paypal", "stripe"}:
        return "Real-money and billing hosts are denied"
    if labels & {"prod", "production"}:
        return "Production-looking hosts are denied"
    return None


def _iter_urls(config: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key in ("base_url", "url", "app_url", "api_url"):
        value = config.get(key)
        if isinstance(value, str) and "://" in value:
            found.append(value)
    script = config.get("script")
    if isinstance(script, list):
        for step in script:
            if not isinstance(step, dict):
                continue
            for key in ("url", "path"):
                value = step.get(key)
                if isinstance(value, str) and "://" in value:
                    found.append(value)
    return found


def _destructive_operations(config: dict[str, Any]) -> list[str]:
    script = config.get("script")
    if not isinstance(script, list):
        return []
    found = []
    for step in script:
        if not isinstance(step, dict) or step.get("action") != "request":
            continue
        method = str(step.get("method") or "GET").upper()
        path = str(step.get("path") or "/")
        normalized_path = path.split("?", 1)[0].lower()
        if any(marker in normalized_path for marker in DESTRUCTIVE_PATH_MARKERS):
            found.append(f"{method} {path}")
        elif method in DESTRUCTIVE_METHODS:
            found.append(f"{method} {path}")
    return found


def _normalize_allowlist(raw: Any) -> dict[str, list[str]]:
    if raw is None:
        return {"origins": [], "accounts": [], "networks": [], "destructive_operations": []}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="allowlist must be an object")
    origins = raw.get("origins") or []
    accounts = raw.get("accounts") or []
    networks = raw.get("networks") or []
    destructive = raw.get("destructive_operations") or []
    if not all(isinstance(item, list) for item in (origins, accounts, networks, destructive)):
        raise HTTPException(status_code=422, detail="allowlist entries must be lists")
    if any(not isinstance(item, str) for item in [*origins, *accounts, *networks, *destructive]):
        raise HTTPException(status_code=422, detail="allowlist entries must be strings")
    return {
        "origins": [_origin(item) for item in origins],
        "accounts": [_normalize_account(item) for item in accounts],
        "networks": [_normalize_network(item) for item in networks],
        "destructive_operations": [item.strip() for item in destructive],
    }


def _normalize_account(value: str) -> str:
    account = value.strip()
    if not _ACCOUNT_NAME.fullmatch(account) or any(word in account.lower() for word in ("password", "secret", "token")):
        raise HTTPException(status_code=422, detail="allowlist accounts must be identifiers, not secrets")
    return account


def _normalize_network(value: str) -> str:
    item = value.strip().lower()
    if "/" in item:
        try:
            return str(ipaddress.ip_network(item, strict=False))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="allowlist networks must be hostnames or CIDRs") from exc
    if not re.fullmatch(r"[a-z0-9.-]{1,253}", item) or item.startswith(".") or item.endswith("."):
        raise HTTPException(status_code=422, detail="allowlist networks must be hostnames or CIDRs")
    return item


def _host_in_networks(hostname: str, networks: list[str]) -> bool:
    host = hostname.lower().rstrip(".")
    for rule in networks:
        if "/" in rule:
            continue
        if host == rule or host.endswith("." + rule):
            return True
    return False


def validate_credential_names(names: Any) -> list[str]:
    if names is None:
        return []
    if not isinstance(names, list) or any(not isinstance(item, str) for item in names):
        raise HTTPException(status_code=422, detail="credential_refs must be a list of names")
    if len(names) > 10:
        raise HTTPException(status_code=422, detail="A task can reference at most 10 credentials")
    normalized = []
    for name in names:
        if not _CREDENTIAL_NAME.fullmatch(name):
            raise HTTPException(status_code=422, detail="credential_refs must be reference names, not secret values")
        normalized.append(name)
    return normalized


def enforce_task_policy(config: dict[str, Any], environment_type: str | None) -> dict[str, Any]:
    """Return the normalized allowlist or raise when the task targets a denied surface."""
    if environment_type and environment_type.strip().lower() in PRODUCTION_ENVIRONMENT_TYPES:
        raise HTTPException(status_code=403, detail="Production environments are denied by default")
    allowlist = _normalize_allowlist(config.get("allowlist"))
    account_ref = config.get("account_ref")
    if account_ref is not None:
        account = _normalize_account(str(account_ref))
        if account not in allowlist["accounts"]:
            raise HTTPException(status_code=422, detail="account_ref must be listed in allowlist.accounts")
    validate_credential_names(config.get("credential_refs"))
    auth = config.get("auth")
    if auth is not None:
        if not isinstance(auth, dict) or auth.get("type") not in {"bearer", "header"}:
            raise HTTPException(status_code=422, detail="auth must reference a bearer or header credential")
        validate_credential_names([auth.get("credential_ref")])
        if auth.get("type") == "header":
            header = str(auth.get("header") or "")
            if not re.fullmatch(r"[A-Za-z0-9-]{1,40}", header):
                raise HTTPException(status_code=422, detail="auth header name is invalid")

    for raw_url in _iter_urls(config):
        parsed = urlparse(raw_url)
        if parsed.username or parsed.password:
            raise HTTPException(status_code=422, detail="Target URLs cannot embed credentials")
        if not parsed.hostname:
            raise HTTPException(status_code=422, detail="Target URL is invalid")
        denied = _host_denied(parsed.hostname)
        if denied:
            raise HTTPException(status_code=403, detail=denied)
        origin = _origin(f"{parsed.scheme}://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else ""))
        if allowlist["origins"] and origin not in allowlist["origins"]:
            raise HTTPException(status_code=422, detail="Target origin is not in the explicit allowlist")
        if allowlist["networks"] and not _host_in_networks(parsed.hostname, allowlist["networks"]):
            raise HTTPException(status_code=422, detail="Target host is not in the explicit network allowlist")

    destructive = _destructive_operations(config)
    for operation in destructive:
        path = operation.split(" ", 1)[1].split("?", 1)[0].lower()
        if any(marker in path for marker in DESTRUCTIVE_PATH_MARKERS):
            raise HTTPException(status_code=403, detail="Destructive payment operations are denied")
        if operation not in allowlist["destructive_operations"]:
            raise HTTPException(
                status_code=422,
                detail="Destructive operations require an explicit allowlist.destructive_operations entry",
            )
    return allowlist
