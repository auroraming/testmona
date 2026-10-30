"""Hardened stdio transport configuration for the Playwright MCP server."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from fastmcp.client.transports import StdioTransport

PLAYWRIGHT_SAFE_TOOLS = frozenset({
    "browser_navigate", "browser_navigate_back", "browser_snapshot", "browser_find",
    "browser_click", "browser_type", "browser_fill_form", "browser_select_option",
    "browser_press_key", "browser_wait_for", "browser_take_screenshot",
    "browser_console_messages", "browser_network_requests", "browser_network_request", "browser_tabs",
})
_PINNED_PACKAGE = re.compile(r"^@playwright/mcp@\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def build_playwright_mcp_transport(*, package_ref: str, allowed_origin: str, workspace: str | Path, command: str = "npx") -> StdioTransport:
    """Build an isolated, headless MCP process without unsafe tool capabilities."""
    if not _PINNED_PACKAGE.fullmatch(package_ref):
        raise ValueError("package_ref must pin an exact @playwright/mcp semantic version")
    parsed = urlparse(allowed_origin)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("allowed_origin must be an http(s) origin without credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("allowed_origin cannot include a path, query, or fragment")
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise ValueError("workspace must be an existing directory")
    origin = f"{parsed.scheme}://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")
    return StdioTransport(
        command=command,
        args=["--yes", package_ref, "--headless", "--isolated", "--browser=chrome", "--block-service-workers", f"--allowed-origins={origin}", "--idle-timeout=300000"],
        cwd=str(root),
        keep_alive=True,
    )
