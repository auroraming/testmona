"""Hardened stdio transport configuration for the Playwright MCP server."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fastmcp.client.transports import StdioTransport

from .automation_origins import normalize_http_origin

PLAYWRIGHT_SAFE_TOOLS = frozenset({
    "browser_navigate", "browser_navigate_back", "browser_snapshot", "browser_find",
    "browser_click", "browser_type", "browser_fill_form", "browser_select_option",
    "browser_press_key", "browser_wait_for", "browser_take_screenshot",
    "browser_console_messages", "browser_network_requests", "browser_network_request", "browser_tabs",
})
_PINNED_PACKAGE = re.compile(r"^@playwright/mcp@\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def build_playwright_mcp_transport(
    *,
    package_ref: str,
    allowed_origin: str,
    workspace: str | Path,
    command: str = "node",
    output_dir: str | Path | None = None,
) -> StdioTransport:
    """Build the same isolated MCP arguments the Node Web Runner launches.

    Production does not use this transport. The container starts
    ``@playwright/mcp`` through ``runners/web/src/mcpWorker.js`` with
    playwright-core 1.64.1, so the browser revision matches the image.
    """
    if not _PINNED_PACKAGE.fullmatch(package_ref):
        raise ValueError("package_ref must pin an exact @playwright/mcp semantic version")
    origin = normalize_http_origin(allowed_origin)
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise ValueError("workspace must be an existing directory")
    output = Path(output_dir) if output_dir is not None else Path(tempfile.mkdtemp(prefix="testmona-mcp-"))
    output.mkdir(parents=True, exist_ok=True)
    return StdioTransport(
        command=command,
        args=[
            "--headless",
            "--isolated",
            "--caps=devtools",
            "--block-service-workers",
            f"--allowed-origins={origin}",
            "--idle-timeout=300000",
            "--image-responses=omit",
            f"--output-dir={output}",
        ],
        cwd=str(output),
        keep_alive=True,
    )
