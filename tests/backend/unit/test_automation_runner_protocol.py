import json

import httpx
import pytest

from app.services.automation_agent_runtime import AgentRuntimeResult, AgentStep
from app.services.automation_runner_protocol import AutomationRunnerProtocol


@pytest.mark.asyncio
async def test_runner_protocol_claim_heartbeat_evidence_and_report():
    requests = []

    async def handler(request):
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body, request.headers.get("x-runner-token")))
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={
                "task": {"id": 7, "max_steps": 5},
                "lease_token": "lease-value",
                "context": {"goal": "Verify login"},
            })
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"runner_status": "online", "cancel_requested": False})
        if request.url.path.endswith("/evidence"):
            return httpx.Response(200, json=body["items"])
        return httpx.Response(200, json={"id": 7, "status": body["status"]})

    protocol = AutomationRunnerProtocol(
        "https://testmona.example",
        "tmr_abcdefghijklmnopqrstuvwxyz",
        transport=httpx.MockTransport(handler),
    )
    try:
        lease = await protocol.claim()
        assert lease.context["goal"] == "Verify login"
        assert (await protocol.heartbeat(lease))["cancel_requested"] is False
        sink = protocol.evidence_sink(lease)
        await sink(AgentStep(1, "browser_click", {"selector": "#go"}, {"ok": True}))
        reported = await protocol.report(lease, AgentRuntimeResult(
            status="completed", summary="done", steps=[AgentStep(1, "browser_click", {})],
            input_tokens=12, output_tokens=4,
        ))
        assert reported["status"] == "passed"
    finally:
        await protocol.aclose()

    assert all(item[3] == "tmr_abcdefghijklmnopqrstuvwxyz" for item in requests)
    evidence = next(item for item in requests if item[1].endswith("/evidence"))
    assert evidence[2]["items"][0]["status"] == "completed"
    report = next(item for item in requests if item[1].endswith("/report"))
    assert report[2]["input_tokens"] == 12


@pytest.mark.asyncio
async def test_runner_protocol_handles_empty_queue():
    protocol = AutomationRunnerProtocol(
        "http://localhost:8000",
        "tmr_abcdefghijklmnopqrstuvwxyz",
        transport=httpx.MockTransport(lambda _request: httpx.Response(204)),
    )
    try:
        assert await protocol.claim() is None
    finally:
        await protocol.aclose()
