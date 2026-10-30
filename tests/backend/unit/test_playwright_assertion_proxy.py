import pytest

from app.services.automation_mcp_client import AutomationMCPError, AutomationMCPTool
from app.services.playwright_assertion_proxy import PlaywrightAssertionProxy


class FakeBrowser:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def health(self):
        return True

    async def discover_tools(self):
        return [
            AutomationMCPTool("browser_snapshot", "snapshot", {"type": "object"}),
            AutomationMCPTool("browser_navigate", "navigate", {"type": "object"}),
            AutomationMCPTool("browser_network_requests", "network", {"type": "object"}),
            AutomationMCPTool("browser_network_request", "network detail", {"type": "object"}),
            AutomationMCPTool("browser_run_code_unsafe", "unsafe", {"type": "object"}),
            AutomationMCPTool("browser_tabs", "tabs", {"type": "object"}),
        ]

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.pages.get(name, {"content": [{"type": "text", "text": ""}]})


def proxy_for(pages):
    browser = FakeBrowser(pages)
    return PlaywrightAssertionProxy(browser, allowed_origin="https://example.test"), browser


@pytest.mark.asyncio
async def test_discovery_adds_assertions_and_hides_unsafe_tools():
    proxy, _browser = proxy_for({})
    names = [tool.name for tool in await proxy.discover_tools()]
    assert "browser_assert_text" in names
    assert "browser_assert_network" in names
    assert "browser_run_code_unsafe" not in names
    assert "browser_network_request" not in names


@pytest.mark.asyncio
async def test_text_and_visibility_assertions_are_explicit():
    snapshot = {"content": [{"type": "text", "text": '- heading "Welcome"\n- button "Sign in"'}]}
    proxy, browser = proxy_for({"browser_snapshot": snapshot})
    passed = await proxy.call_tool("browser_assert_text", {"expected": "Welcome"})
    visible = await proxy.call_tool("browser_assert_visible", {"name": "Sign in"})
    missing = await proxy.call_tool("browser_assert_text", {"expected": "Goodbye"})
    assert passed["structured_content"]["passed"] is True
    assert visible["structured_content"]["passed"] is True
    assert missing["structured_content"]["passed"] is False
    assert all(call[0] == "browser_snapshot" for call in browser.calls)


@pytest.mark.asyncio
async def test_url_assertion_stays_on_allowed_origin():
    tabs = {"content": [{"type": "text", "text": "- 0: (current) [Home](https://example.test/login)"}]}
    proxy, _browser = proxy_for({"browser_tabs": tabs})
    assert (await proxy.call_tool("browser_assert_url", {"expected": "/login"}))["structured_content"]["passed"] is True
    assert (await proxy.call_tool("browser_assert_url", {"expected": "https://example.test/login"}))["structured_content"]["passed"] is True
    other = await proxy.call_tool("browser_assert_url", {"expected": "https://evil.test/login"})
    assert other["structured_content"]["passed"] is False


@pytest.mark.asyncio
async def test_network_assertion_ignores_other_origins():
    network = {"content": [{"type": "text", "text": "\n".join([
        "[GET] https://example.test/api/orders => [201] Created",
        "[GET] https://evil.test/api/orders => [201] Created",
    ])}]}
    proxy, browser = proxy_for({"browser_network_requests": network})
    passed = await proxy.call_tool("browser_assert_network", {"url_contains": "/api/orders", "method": "GET", "status": 201})
    rejected = await proxy.call_tool("browser_assert_network", {"url_contains": "https://evil.test", "status": 201})
    assert passed["structured_content"]["passed"] is True
    assert rejected["structured_content"]["passed"] is False
    assert browser.calls[0][1] == {"static": False}


@pytest.mark.asyncio
async def test_navigation_outside_origin_is_not_sent_to_the_browser():
    proxy, browser = proxy_for({})
    with pytest.raises(AutomationMCPError) as exc_info:
        await proxy.call_tool("browser_navigate", {"url": "https://evil.test/steal", "filename": "note.txt", "token": "secret"})
    assert exc_info.value.code == "origin_forbidden"
    assert browser.calls == []
    await proxy.call_tool("browser_navigate", {"url": "https://example.test/login", "filename": "note.txt"})
    assert browser.calls == [("browser_navigate", {"url": "https://example.test/login"})]


@pytest.mark.asyncio
async def test_unsafe_and_detail_tools_are_forbidden():
    proxy, browser = proxy_for({})
    with pytest.raises(AutomationMCPError) as unsafe:
        await proxy.call_tool("browser_run_code_unsafe", {"code": "process.exit(1)"})
    with pytest.raises(AutomationMCPError) as detail:
        await proxy.call_tool("browser_network_request", {"index": 1})
    assert unsafe.value.code == "tool_forbidden"
    assert detail.value.code == "tool_forbidden"
    assert browser.calls == []


@pytest.mark.asyncio
async def test_tool_results_drop_images_and_secret_keys():
    proxy, _browser = proxy_for({"browser_snapshot": {
        "content": [
            {"type": "image", "data": "aaaa"},
            {"type": "text", "text": "visible", "authorization": "Bearer secret"},
        ],
    }})
    result = await proxy.call_tool("browser_snapshot", {})
    assert result["content"][0] == {"type": "text", "text": "[image omitted from the model context]"}
    assert "authorization" not in result["content"][1]
