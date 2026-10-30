"""Explicit assertions in front of the Playwright MCP browser tools.

Playwright MCP can navigate and observe a page, but it does not publish
assertion tools. A click or navigation must not be able to pass a task. This
proxy adds text, visibility, URL, and network assertions, and it refuses
navigation outside the task origin. Upstream ``--allowed-origins`` is not
treated as a security boundary.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from jsonschema import ValidationError, validate

from .automation_mcp_client import AutomationMCPError, AutomationMCPTool, strip_inline_secrets
from .playwright_mcp_transport import PLAYWRIGHT_SAFE_TOOLS

PROXY_HIDDEN_TOOLS = frozenset({"browser_network_request"})
_DROPPED_ARGUMENT_KEYS = frozenset({"filename", "code"})
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_SENSITIVE_QUERY_KEYS = {
    "token", "access_token", "api_key", "apikey", "password", "secret",
    "authorization", "key", "sig", "signature",
}
_URL_RE = re.compile(r"https?://[^\s\]\)\"'<>]+")
_REQUEST_RE = re.compile(
    r"\b(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b[^\n]{0,80}?(?P<url>https?://[^\s\]\)\"'<>]+)",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(r"\[(\d{3})\]")

ASSERTION_TOOL_SPECS: dict[str, dict[str, Any]] = {
    "browser_assert_text": {
        "description": "Assert the current page snapshot contains the expected text. This is an explicit assertion.",
        "input_schema": {
            "type": "object",
            "properties": {"expected": {"type": "string", "minLength": 1, "maxLength": 500}},
            "required": ["expected"],
            "additionalProperties": False,
        },
    },
    "browser_assert_visible": {
        "description": "Assert an accessible name is present as a quoted label in the current page snapshot.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 300}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "browser_assert_url": {
        "description": "Assert the active tab URL matches a path or absolute URL on the allowed origin.",
        "input_schema": {
            "type": "object",
            "properties": {"expected": {"type": "string", "minLength": 1, "maxLength": 2000}},
            "required": ["expected"],
            "additionalProperties": False,
        },
    },
    "browser_assert_network": {
        "description": "Assert a captured same-origin network request matches the URL fragment, method, and status. Does not issue a new request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url_contains": {"type": "string", "minLength": 1, "maxLength": 500},
                "method": {"type": "string", "minLength": 3, "maxLength": 10},
                "status": {"type": "integer", "minimum": 100, "maximum": 599},
            },
            "required": ["url_contains"],
            "additionalProperties": False,
        },
    },
}


def normalize_http_origin(value: str) -> str:
    """Return a scheme/host/port origin, rejecting credentials and extra URL parts."""
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL must be an http(s) origin without credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("URL must be an origin without a path, query, or fragment")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def request_origin(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        hostname = parsed.hostname or ""
        netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
        parsed = parsed._replace(netloc=netloc)
    query = urlencode([
        (key, "[redacted]" if key.lower() in _SENSITIVE_QUERY_KEYS else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ])
    return urlunparse(parsed._replace(query=query))


def content_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
    return "\n".join(parts)


def observation_text(result: dict[str, Any]) -> str:
    parts = [content_text(result)]
    structured = result.get("structured_content")
    if structured not in (None, {}, []):
        parts.append(json.dumps(strip_inline_secrets(structured), ensure_ascii=False)[:8000])
    return "\n".join(part for part in parts if part)


def sanitize_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    content = []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "image":
            content.append({"type": "text", "text": "[image omitted from the model context]"})
            continue
        copied = strip_inline_secrets(item)
        if isinstance(copied, dict) and isinstance(copied.get("text"), str):
            copied["text"] = copied["text"][:8000]
        content.append(copied)
    return {
        "structured_content": strip_inline_secrets(result.get("structured_content")),
        "content": content,
    }


def extract_current_url(result: dict[str, Any]) -> str | None:
    structured = result.get("structured_content")
    tabs = None
    if isinstance(structured, dict):
        candidate = structured.get("tabs") or structured.get("items")
        tabs = candidate if isinstance(candidate, list) else None
    elif isinstance(structured, list):
        tabs = structured
    if isinstance(tabs, list):
        fallback = None
        for tab in tabs:
            if not isinstance(tab, dict) or not isinstance(tab.get("url"), str):
                continue
            if tab.get("current") is True or tab.get("active") is True or tab.get("selected") is True:
                return tab["url"]
            fallback = fallback or tab["url"]
        if fallback:
            return fallback
    text = content_text(result)
    current_lines = [line for line in text.splitlines() if "current" in line.lower()]
    for line in current_lines or text.splitlines():
        match = _URL_RE.search(line)
        if match:
            return match.group(0)
    return None


def extract_network_requests(result: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    structured = result.get("structured_content")
    items: list[Any] = []
    if isinstance(structured, dict):
        raw = structured.get("requests") or structured.get("items") or []
        if isinstance(raw, list):
            items = raw
    elif isinstance(structured, list):
        items = structured
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            status = item.get("status")
            found.append({
                "method": str(item.get("method") or "GET").upper(),
                "url": item["url"],
                "status": status if isinstance(status, int) else None,
            })
    for line in content_text(result).splitlines():
        match = _REQUEST_RE.search(line)
        if match is None:
            continue
        status_match = _STATUS_RE.search(line)
        found.append({
            "method": match.group("method").upper(),
            "url": match.group("url"),
            "status": int(status_match.group(1)) if status_match else None,
        })
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int | None]] = set()
    for item in found:
        key = (item["method"], item["url"], item["status"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def url_matches(expected: str, current: str | None, allowed_origin: str) -> bool:
    if not current or request_origin(current) != allowed_origin:
        return False
    expected = expected.strip()
    current_parts = urlparse(current)
    if expected.startswith("/") and not expected.startswith("//") and "\\" not in expected and ".." not in expected.split("/"):
        path, _, query = expected.partition("?")
        if current_parts.path.rstrip("/") != path.rstrip("/"):
            return False
        return not query or current_parts.query == query
    if request_origin(expected) != allowed_origin:
        return False
    expected_parts = urlparse(expected)
    return (
        current_parts.path.rstrip("/") == expected_parts.path.rstrip("/")
        and current_parts.query == expected_parts.query
    )


class PlaywrightAssertionProxy:
    """Agent-facing MCP client with local assertions and a navigation allowlist."""

    def __init__(self, client: Any, *, allowed_origin: str) -> None:
        self.client = client
        self.allowed_origin = normalize_http_origin(allowed_origin)

    async def health(self) -> bool:
        return await self.client.health()

    async def discover_tools(self) -> list[AutomationMCPTool]:
        remote = await self.client.discover_tools()
        visible = [
            tool for tool in remote
            if tool.name in PLAYWRIGHT_SAFE_TOOLS and tool.name not in PROXY_HIDDEN_TOOLS
        ]
        visible.sort(key=lambda tool: tool.name)
        return visible + [
            AutomationMCPTool(name, spec["description"], spec["input_schema"])
            for name, spec in ASSERTION_TOOL_SPECS.items()
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = arguments or {}
        if name in ASSERTION_TOOL_SPECS:
            self._validate(name, payload)
            return await self._assert(name, payload)
        if name not in PLAYWRIGHT_SAFE_TOOLS or name in PROXY_HIDDEN_TOOLS:
            raise AutomationMCPError("tool_forbidden", f"Tool '{name}' is not authorized for this task")
        sanitized = self._sanitize_arguments(name, payload)
        self._enforce_navigation(name, sanitized)
        result = await self.client.call_tool(name, sanitized)
        return sanitize_tool_result(result if isinstance(result, dict) else {})

    def _validate(self, name: str, arguments: dict[str, Any]) -> None:
        try:
            validate(instance=arguments, schema=ASSERTION_TOOL_SPECS[name]["input_schema"])
        except ValidationError as exc:
            raise AutomationMCPError("invalid_arguments", f"Invalid arguments: {exc.message}") from exc

    def _sanitize_arguments(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = strip_inline_secrets(dict(arguments))
        if not isinstance(payload, dict):
            return {}
        for key in list(payload):
            if str(key).lower() in _DROPPED_ARGUMENT_KEYS:
                del payload[key]
        if name == "browser_network_requests":
            payload.pop("filter", None)
            payload.pop("filename", None)
            if "static" in payload and not isinstance(payload["static"], bool):
                del payload["static"]
        return payload

    def _enforce_navigation(self, name: str, arguments: dict[str, Any]) -> None:
        if name == "browser_navigate":
            url = arguments.get("url")
            if not isinstance(url, str) or request_origin(url) != self.allowed_origin:
                raise AutomationMCPError("origin_forbidden", "Navigation target is outside the allowed origin")
        if name == "browser_tabs" and arguments.get("action") == "new" and arguments.get("url") is not None:
            url = arguments.get("url")
            if not isinstance(url, str) or request_origin(url) != self.allowed_origin:
                raise AutomationMCPError("origin_forbidden", "New tab URL is outside the allowed origin")

    async def _observe(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self.client.call_tool(name, arguments)
        return sanitize_tool_result(result if isinstance(result, dict) else {})

    async def _assert(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "browser_assert_text":
            expected = str(arguments["expected"]).strip()
            if not expected:
                raise AutomationMCPError("invalid_arguments", "expected text cannot be blank")
            observed = await self._observe("browser_snapshot", {})
            text = observation_text(observed)
            return _assertion_result(expected in text, expected, text[:2000])
        if name == "browser_assert_visible":
            label = str(arguments["name"]).strip()
            if not label:
                raise AutomationMCPError("invalid_arguments", "accessible name cannot be blank")
            observed = await self._observe("browser_snapshot", {})
            text = observation_text(observed)
            passed = f'"{label}"' in text or f"'{label}'" in text
            return _assertion_result(passed, label, text[:2000])
        if name == "browser_assert_url":
            expected = str(arguments["expected"]).strip()
            if not expected:
                raise AutomationMCPError("invalid_arguments", "expected URL cannot be blank")
            observed = await self._observe("browser_tabs", {"action": "list"})
            current = extract_current_url(observed)
            return _assertion_result(
                url_matches(expected, current, self.allowed_origin),
                expected,
                redact_url(current) if current else None,
            )
        method = arguments.get("method")
        if method is not None and str(method).upper() not in _HTTP_METHODS:
            raise AutomationMCPError("invalid_arguments", "Unsupported HTTP method")
        needle = str(arguments["url_contains"]).strip()
        if not needle:
            raise AutomationMCPError("invalid_arguments", "url_contains cannot be blank")
        observed = await self._observe("browser_network_requests", {"static": False})
        requests = extract_network_requests(observed)
        normalized = dict(arguments)
        normalized["url_contains"] = needle
        if method is not None:
            normalized["method"] = str(method).upper()
        matched = _find_network_match(requests, normalized, self.allowed_origin)
        actual = [
            {"method": item["method"], "url": redact_url(item["url"]), "status": item["status"]}
            for item in requests
            if request_origin(item["url"]) == self.allowed_origin
        ][:20]
        expected = {
            key: normalized[key]
            for key in ("url_contains", "method", "status")
            if key in normalized and normalized[key] is not None
        }
        return _assertion_result(matched is not None, expected, actual)


def _find_network_match(requests: list[dict[str, Any]], arguments: dict[str, Any], allowed_origin: str) -> dict[str, Any] | None:
    method = arguments.get("method")
    status = arguments.get("status")
    needle = arguments["url_contains"]
    for item in requests:
        if request_origin(item["url"]) != allowed_origin or needle not in item["url"]:
            continue
        if method and item["method"] != method:
            continue
        if status is not None and item["status"] != status:
            continue
        return item
    return None


def _assertion_result(passed: bool, expected: Any, actual: Any) -> dict[str, Any]:
    outcome = True if passed else False
    return {
        "structured_content": {"passed": outcome, "expected": expected, "actual": actual},
        "content": [{"type": "text", "text": json.dumps({"passed": outcome}, ensure_ascii=False)}],
    }
