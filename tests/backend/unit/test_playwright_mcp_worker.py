from types import SimpleNamespace

import pytest

from app.services.ai_manager import AICompletionResult
from app.services.automation_agent_runtime import AutomationAgentRuntime
from app.services.automation_mcp_client import AutomationMCPError, AutomationMCPTool
from app.services.automation_runner_protocol import RunnerLease
from app.services.playwright_mcp_worker import PlaywrightMCPWorker, run_web_ai_task


class RecordingTransport:
    def __init__(self):
        self.disconnected = False

    async def disconnect(self):
        self.disconnected = True


class HealthyClient:
    def __init__(self, transport):
        self.transport = transport

    async def health(self):
        return True

    async def discover_tools(self):
        return [AutomationMCPTool("browser_snapshot", "snapshot", {"type": "object"})]

    async def call_tool(self, name, arguments):
        return {"content": [{"type": "text", "text": 'heading "Welcome"'}]}


class UnhealthyClient:
    def __init__(self, _transport):
        pass

    async def health(self):
        raise AutomationMCPError("unhealthy", "MCP did not answer", retryable=True)


def lease_with(context, **task):
    payload = {
        "id": 7,
        "project_id": 4,
        "requested_by": 8,
        "execution_mode": "ai",
        "max_steps": 3,
        "timeout_seconds": 30,
        "token_budget": 100,
        "goal": "Check the title",
        "config": {},
    }
    payload.update(task)
    return RunnerLease(payload, "lease-token", context)


class FakeProtocol:
    def __init__(self):
        self.reports = []
        self.evidence = []

    async def report(self, _lease, result):
        self.reports.append(result)
        return {"status": result.status}

    async def heartbeat(self, _lease):
        return {"cancel_requested": False}

    def evidence_sink(self, _lease):
        async def persist(step):
            self.evidence.append(step)
        return persist


@pytest.mark.asyncio
async def test_worker_disconnects_after_use_and_after_failed_health(tmp_path):
    transports = []

    def transport_factory(**_kwargs):
        transport = RecordingTransport()
        transports.append(transport)
        return transport

    worker = PlaywrightMCPWorker(
        package_ref="@playwright/mcp@0.0.83",
        allowed_origin="https://example.test",
        workspace=str(tmp_path),
        transport_factory=transport_factory,
        client_factory=HealthyClient,
    )
    proxy = await worker.start()
    assert any(tool.name == "browser_assert_text" for tool in await proxy.discover_tools())
    await worker.stop()
    await worker.stop()
    assert transports[0].disconnected is True

    sick = PlaywrightMCPWorker(
        package_ref="@playwright/mcp@0.0.83",
        allowed_origin="https://example.test",
        workspace=str(tmp_path),
        transport_factory=transport_factory,
        client_factory=UnhealthyClient,
    )
    with pytest.raises(AutomationMCPError):
        await sick.start()
    assert transports[1].disconnected is True


@pytest.mark.asyncio
async def test_missing_origin_does_not_start_worker_and_reports_blocked():
    protocol = FakeProtocol()

    def factory(**_kwargs):
        raise AssertionError("worker should not start")

    result = await run_web_ai_task(
        protocol,
        lease_with({}),
        workspace="/tmp",
        completion=lambda *_args, **_kwargs: None,
        worker_factory=factory,
    )
    assert result.status == "blocked"
    assert result.error["code"] == "blocked"
    assert protocol.reports == [result]


@pytest.mark.asyncio
async def test_runtime_requires_assertion_and_worker_always_stops():
    protocol = FakeProtocol()
    stopped = []

    class Browser:
        async def health(self):
            return True

        async def discover_tools(self):
            return [
                AutomationMCPTool("browser_click", "click", {"type": "object"}),
                AutomationMCPTool("browser_snapshot", "snapshot", {"type": "object"}),
            ]

        async def call_tool(self, name, _arguments):
            if "assert" in name or name == "browser_snapshot":
                return {"content": [{"type": "text", "text": 'heading "Welcome"'}]}
            return {"structured_content": {"clicked": True}, "content": []}

    class Worker:
        def __init__(self, **_kwargs):
            self.client = Browser()

        async def start(self):
            from app.services.playwright_assertion_proxy import PlaywrightAssertionProxy

            return PlaywrightAssertionProxy(self.client, allowed_origin="https://example.test")

        async def stop(self):
            stopped.append(True)

    responses = [
        '{"type":"tool","tool":"browser_click","arguments":{}}',
        '{"type":"finish","summary":"looks fine"}',
    ]

    async def completion(*_args, **_kwargs):
        return AICompletionResult(
            provider="fake", model="fake", content=responses.pop(0),
            prompt_tokens=1, completion_tokens=1, total_tokens=2,
        )

    result = await run_web_ai_task(
        protocol,
        lease_with({"environment": {"config": {"app_url": "https://example.test"}}}),
        workspace="/tmp",
        completion=completion,
        worker_factory=Worker,
        runtime_factory=AutomationAgentRuntime,
    )
    assert result.status == "failed"
    assert result.error["code"] == "missing_assertion"
    assert stopped == [True]
    assert protocol.reports[0].status == "failed"
    assert protocol.evidence


@pytest.mark.asyncio
async def test_worker_start_failure_reports_blocked_after_stop():
    protocol = FakeProtocol()
    stopped = []

    class Worker:
        def __init__(self, **_kwargs):
            pass

        async def start(self):
            raise RuntimeError("browser down")

        async def stop(self):
            stopped.append(True)

    result = await run_web_ai_task(
        protocol,
        lease_with({"environment": {"config": {"base_url": "https://example.test"}}}),
        workspace="/tmp",
        completion=lambda *_args, **_kwargs: None,
        db=SimpleNamespace(),
        worker_factory=Worker,
    )
    assert result.status == "blocked"
    assert result.error["code"] == "worker_unavailable"
    assert stopped == [True]


@pytest.mark.asyncio
async def test_passing_assertion_lets_the_runtime_finish():
    protocol = FakeProtocol()

    class Browser:
        async def health(self):
            return True

        async def discover_tools(self):
            return [AutomationMCPTool("browser_snapshot", "snapshot", {"type": "object"})]

        async def call_tool(self, _name, _arguments):
            return {"content": [{"type": "text", "text": 'heading "Welcome"'}]}

    class Worker:
        def __init__(self, **_kwargs):
            pass

        async def start(self):
            from app.services.playwright_assertion_proxy import PlaywrightAssertionProxy

            return PlaywrightAssertionProxy(Browser(), allowed_origin="https://example.test")

        async def stop(self):
            return None

    responses = [
        '{"type":"tool","tool":"browser_assert_text","arguments":{"expected":"Welcome"}}',
        '{"type":"finish","summary":"Title is visible"}',
    ]

    async def completion(*_args, **_kwargs):
        return AICompletionResult(
            provider="fake", model="fake", content=responses.pop(0),
            prompt_tokens=2, completion_tokens=3, total_tokens=5,
        )

    result = await run_web_ai_task(
        protocol,
        lease_with({"goal": "Check the title", "environment": {"config": {"app_url": "https://example.test"}}}),
        workspace="/tmp",
        completion=completion,
        worker_factory=Worker,
    )
    assert result.status == "completed"
    assert result.summary == "Title is visible"
    assert result.input_tokens == 4
    assert protocol.evidence[0].tool == "browser_assert_text"
