import asyncio
from types import SimpleNamespace

import pytest

from app.services.automation_mcp_client import AutomationMCPClient, AutomationMCPError


class FakeResult:
    def __init__(self, *, is_error=False):
        self.is_error = is_error
        self.structured_content = {"ok": not is_error}
        self.content = []


class FakeClient:
    tools = [
        SimpleNamespace(
            name="browser_click",
            description="Click one element",
            input_schema={
                "type": "object",
                "properties": {"selector": {"type": "string"}},
                "required": ["selector"],
                "additionalProperties": False,
            },
        ),
        SimpleNamespace(name="admin_delete", description="Unsafe", input_schema={"type": "object"}),
    ]
    calls = []

    def __init__(self, _transport, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def ping(self):
        return True

    async def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments, **_kwargs):
        self.calls.append((name, arguments))
        return FakeResult()


@pytest.mark.asyncio
async def test_health_and_discovery_only_expose_task_allowlist():
    client = AutomationMCPClient("memory", allowed_tools={"browser_click"}, client_factory=FakeClient)
    assert await client.health() is True
    tools = await client.discover_tools()
    assert [tool.name for tool in tools] == ["browser_click"]


@pytest.mark.asyncio
async def test_call_validates_schema_before_invocation():
    FakeClient.calls = []
    client = AutomationMCPClient("memory", allowed_tools={"browser_click"}, client_factory=FakeClient)

    with pytest.raises(AutomationMCPError) as exc_info:
        await client.call_tool("browser_click", {})
    assert exc_info.value.code == "invalid_arguments"
    assert FakeClient.calls == []

    result = await client.call_tool("browser_click", {"selector": "#submit"})
    assert result["structured_content"] == {"ok": True}
    assert FakeClient.calls == [("browser_click", {"selector": "#submit"})]


@pytest.mark.asyncio
async def test_call_rejects_tools_outside_task_permission():
    client = AutomationMCPClient("memory", allowed_tools={"browser_click"}, client_factory=FakeClient)
    with pytest.raises(AutomationMCPError) as exc_info:
        await client.call_tool("admin_delete", {})
    assert exc_info.value.code == "tool_forbidden"


@pytest.mark.asyncio
async def test_timeout_is_normalized_as_retryable_error():
    class SlowClient(FakeClient):
        async def ping(self):
            await asyncio.sleep(0.05)
            return True

    client = AutomationMCPClient(
        "memory", allowed_tools={"browser_click"}, timeout_seconds=0.01, client_factory=SlowClient
    )
    with pytest.raises(AutomationMCPError) as exc_info:
        await client.health()
    assert exc_info.value.as_dict() == {
        "code": "timeout",
        "message": "MCP operation timed out",
        "retryable": True,
    }
