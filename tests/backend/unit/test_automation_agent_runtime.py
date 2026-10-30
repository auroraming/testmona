from types import SimpleNamespace

import pytest

from app.services.ai_manager import AICompletionResult
from app.services.automation_agent_runtime import AutomationAgentRuntime
from app.services.automation_mcp_client import AutomationMCPTool


class FakeMCP:
    def __init__(self):
        self.calls = []

    async def health(self):
        return True

    async def discover_tools(self):
        return [
            AutomationMCPTool("browser_click", "click", {"type": "object"}),
            AutomationMCPTool("browser_assert_visible", "assert visible", {"type": "object"}),
        ]

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if "assert" in name:
            return {"structured_content": {"passed": True}, "content": []}
        return {"structured_content": {"clicked": True}, "content": []}


def completion_sequence(*contents, tokens=10):
    queue = list(contents)

    async def complete(*_args, **_kwargs):
        return AICompletionResult(
            provider="fake",
            model="fake",
            content=queue.pop(0),
            prompt_tokens=tokens,
            completion_tokens=tokens,
            total_tokens=tokens * 2,
        )

    return complete


@pytest.mark.asyncio
async def test_runtime_calls_allowed_tool_then_finishes():
    mcp = FakeMCP()
    observed = []

    async def capture(step):
        observed.append(step)

    runtime = AutomationAgentRuntime(
        SimpleNamespace(), mcp, project_id=1, user_id=2, max_steps=3, timeout_seconds=30,
        token_budget=100, completion=completion_sequence(
            '{"type":"tool","tool":"browser_assert_visible","arguments":{"selector":"#go"}}',
            '{"type":"finish","summary":"Assertion completed"}',
        ), step_callback=capture,
    )
    result = await runtime.run("Open the page")
    assert result.status == "completed"
    assert result.summary == "Assertion completed"
    assert result.input_tokens == 20
    assert mcp.calls == [("browser_assert_visible", {"selector": "#go"})]
    assert [(step.sequence, step.tool) for step in observed] == [(1, "browser_assert_visible")]


@pytest.mark.asyncio
async def test_runtime_refuses_to_finish_without_passing_assertion():
    runtime = AutomationAgentRuntime(
        SimpleNamespace(), FakeMCP(), project_id=1, user_id=2, max_steps=3, timeout_seconds=30,
        completion=completion_sequence(
            '{"type":"tool","tool":"browser_click","arguments":{"selector":"#go"}}',
            '{"type":"finish","summary":"looks good"}',
        ),
    )
    result = await runtime.run("Open the page")
    assert result.status == "failed"
    assert result.error["code"] == "missing_assertion"


@pytest.mark.asyncio
async def test_runtime_stops_on_cancellation_before_model_call():
    calls = 0

    async def cancelled():
        return True

    async def should_not_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1

    runtime = AutomationAgentRuntime(
        SimpleNamespace(), FakeMCP(), project_id=1, user_id=2, max_steps=3, timeout_seconds=30,
        completion=should_not_run, cancellation_check=cancelled,
    )
    result = await runtime.run("Stop")
    assert result.status == "cancelled"
    assert calls == 0


@pytest.mark.asyncio
async def test_runtime_enforces_token_budget_and_structures_failure():
    runtime = AutomationAgentRuntime(
        SimpleNamespace(), FakeMCP(), project_id=1, user_id=2, max_steps=3, timeout_seconds=30,
        token_budget=15, completion=completion_sequence('{"type":"finish","summary":"done"}', tokens=10),
    )
    result = await runtime.run("Budgeted")
    assert result.status == "failed"
    assert result.error["code"] == "token_budget_exceeded"


@pytest.mark.asyncio
async def test_runtime_rejects_invalid_model_protocol():
    runtime = AutomationAgentRuntime(
        SimpleNamespace(), FakeMCP(), project_id=1, user_id=2, max_steps=1, timeout_seconds=30,
        completion=completion_sequence('{"type":"unknown"}'),
    )
    result = await runtime.run("Invalid")
    assert result.status == "failed"
    assert result.error["code"] == "invalid_model_output"
