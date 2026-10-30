"""Async client for the private TestMona automation Runner protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from .automation_agent_runtime import AgentRuntimeResult, AgentStep
from .automation_mcp_client import strip_inline_secrets


class RunnerProtocolError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class RunnerLease:
    task: dict[str, Any]
    lease_token: str
    context: dict[str, Any]


class AutomationRunnerProtocol:
    """Keeps Runner authentication and lease operations in one small SDK."""

    def __init__(
        self,
        base_url: str,
        runner_token: str,
        *,
        timeout_seconds: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an http(s) URL with a host")
        if not runner_token.startswith("tmr_") or len(runner_token) < 20:
            raise ValueError("runner_token is invalid")
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-Runner-Token": runner_token},
            timeout=timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> "AutomationRunnerProtocol":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self.client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RunnerProtocolError("transport_error", "TestMona backend is unavailable", retryable=True) from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", "Runner protocol request failed")
            except (ValueError, AttributeError):
                detail = "Runner protocol request failed"
            raise RunnerProtocolError(
                "lease_conflict" if response.status_code == 409 else "protocol_error",
                str(detail),
                retryable=response.status_code >= 500,
            )
        return response

    async def claim(self) -> RunnerLease | None:
        response = await self._request("POST", "/internal/ai-automation/claim")
        if response.status_code == 204:
            return None
        data = response.json()
        return RunnerLease(data["task"], data["lease_token"], data.get("context") or {})

    async def heartbeat(self, lease: RunnerLease | None = None) -> dict[str, Any]:
        payload = {}
        if lease is not None:
            payload = {"task_id": lease.task["id"], "lease_token": lease.lease_token}
        return (await self._request("POST", "/internal/ai-automation/heartbeat", json=payload)).json()

    async def append_evidence(self, lease: RunnerLease, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        response = await self._request(
            "POST",
            f"/internal/ai-automation/tasks/{lease.task['id']}/evidence",
            json={"lease_token": lease.lease_token, "items": items},
        )
        return response.json()

    async def report(self, lease: RunnerLease, result: AgentRuntimeResult) -> dict[str, Any]:
        status = {
            "completed": "passed",
            "cancelled": "cancelled",
            "failed": "failed",
            "blocked": "blocked",
            "timed_out": "timed_out",
        }.get(result.status, "failed")
        payload = {
            "lease_token": lease.lease_token,
            "status": status,
            "result": {
                "summary": result.summary,
                "step_count": len(result.steps),
                "error": result.error,
            },
            "error_message": result.error.get("message") if result.error else None,
            "input_tokens": result.input_tokens,
            "cached_tokens": result.cached_tokens,
            "output_tokens": result.output_tokens,
        }
        return (await self._request(
            "POST", f"/internal/ai-automation/tasks/{lease.task['id']}/report", json=payload
        )).json()

    def evidence_sink(self, lease: RunnerLease):
        """Return an Agent Runtime callback that persists one immutable step."""
        async def persist(step: AgentStep) -> None:
            output = step.output if isinstance(step.output, dict) else {}
            structured = output.get("structured_content") if isinstance(output, dict) else None
            text_parts: list[str] = []
            content = output.get("content") if isinstance(output, dict) else None
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                        text_parts.append(item["text"][:2000])
            failed = bool(step.error) or (isinstance(structured, dict) and structured.get("passed") is False)
            await self.append_evidence(lease, [{
                "sequence": step.sequence,
                "evidence_type": _evidence_type_for_tool(step.tool),
                "title": step.tool,
                "status": "failed" if failed else "completed",
                "payload": strip_inline_secrets({
                    "arguments": step.arguments,
                    "output": {
                        "structured_content": structured,
                        "text": "\n".join(text_parts)[:4000],
                    },
                    "error": step.error,
                }),
            }])

        return persist


def _evidence_type_for_tool(tool: str) -> str:
    name = tool.lower()
    if "assert" in name:
        return "assertion"
    if "network" in name:
        return "network"
    if "screenshot" in name:
        return "screenshot"
    if "trace" in name:
        return "trace"
    return "step"
