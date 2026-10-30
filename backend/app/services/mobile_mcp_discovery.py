"""mobile-mcp discovery contract.

This is the tool allowlist TestMona is willing to expose to a future Mobile
Runner. It does not open a device session and must not be treated as Android
or iOS end-to-end coverage.
"""

from __future__ import annotations

import re


_PACKAGE = re.compile(r"^@mobilenext/mobile-mcp@\d+\.\d+\.\d+$")
# Read and gesture tools only. Install, uninstall, and terminate stay out of the
# default allowlist so a discovered server cannot gain those privileges here.
SAFE_MOBILE_MCP_TOOLS = (
    "mobile_list_available_devices",
    "mobile_list_elements_on_screen",
    "mobile_take_screenshot",
    "mobile_click_on_screen_at_coordinates",
    "mobile_swipe_on_screen",
    "mobile_type_keys",
)
IOS_DEPLOYMENT_NOTE = (
    "iOS execution requires a macOS host with Xcode. A generic Linux Docker runner cannot provide it."
)


def validate_mobile_mcp_package(package_ref: str) -> str:
    if not _PACKAGE.fullmatch(package_ref or ""):
        raise ValueError("package_ref must pin an exact @mobilenext/mobile-mcp semantic version")
    return package_ref


def discovery_contract(live_tool_names: list[str] | None = None) -> dict:
    allowed = list(SAFE_MOBILE_MCP_TOOLS)
    if live_tool_names is None:
        return {
            "live": False,
            "mode": "contract",
            "package": "@mobilenext/mobile-mcp",
            "tools": allowed,
            "note": "No device worker is connected. This is the allowlist contract, not a live mobile-mcp session.",
            "ios_deployment_note": IOS_DEPLOYMENT_NOTE,
        }
    exposed = [name for name in live_tool_names if name in SAFE_MOBILE_MCP_TOOLS]
    hidden = [name for name in live_tool_names if name not in SAFE_MOBILE_MCP_TOOLS]
    return {
        "live": True,
        "mode": "filtered",
        "package": "@mobilenext/mobile-mcp",
        "tools": exposed,
        "hidden_tools": hidden,
        "note": "Live tool names were intersected with the TestMona allowlist. Device execution is still a worker responsibility.",
        "ios_deployment_note": IOS_DEPLOYMENT_NOTE,
    }
