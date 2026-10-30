"""Start and stop one Playwright MCP process for a single Web AI task.

The fixed-script Web Runner stays on Playwright 1.64.1. AI exploration uses a
separately pinned ``@playwright/mcp`` package and must not keep that process
alive after the task reaches a terminal result.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any, Callable

from .automation_agent_runtime import AgentRuntimeResult, AutomationAgentRuntime
from .automation_mcp_client import AutomationMCPClient
from .automation_runner_protocol import RunnerLease
from .playwright_assertion_proxy import PlaywrightAssertionProxy, normalize_http_origin
from .playwright_mcp_transport import PLAYWRIGHT_SAFE_TOOLS, build_playwright_mcp_transport

DEFAULT_PLAYWRIGHT_MCP_PACKAGE = "@playwright/mcp@0.0.83"
_PINNED_PACKAGE = re.compile(r"^@playwright/mcp@\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def resolve_web_ai_origin(context: dict[str, Any] | None) -> str:
    environment = context.get("environment") if isinstance(context, dict) else None
    config = environment.get("config") if isinstance(environment, dict) else None
    if not isinstance(config, dict):
        raise ValueError("Web AI tasks require an environment app_url or base_url")
    for key in ("app_url", "base_url"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_http_origin(value)
    raise ValueError("Web AI tasks require an environment app_url or base_url")


def resolve_playwright_package(task: dict[str, Any], override: str | None = None) -> str:
    config = task.get("config") if isinstance(task.get("config"), dict) else {}
    configured = config.get("playwright_mcp_package") if isinstance(config, dict) else None
    if override:
        package = override
    elif isinstance(configured, str) and configured.strip():
        package = configured.strip()
    else:
        package = DEFAULT_PLAYWRIGHT_MCP_PACKAGE
    if not _PINNED_PACKAGE.fullmatch(package):
        raise ValueError("playwright_mcp_package must pin an exact @playwright/mcp semantic version")
    return package


def build_web_ai_goal(lease: RunnerLease) -> str:
    context = lease.context or {}
    parts = [str(context.get("goal") or lease.task.get("goal") or "").strip()]
    test_case = context.get("test_case")
    if isinstance(test_case, dict):
        snapshot = {
            "title": test_case.get("title"),
            "description": test_case.get("description"),
            "preconditions": test_case.get("preconditions"),
            "steps": test_case.get("steps"),
            "expected_result": test_case.get("expected_result"),
            "structured_steps": test_case.get("structured_steps"),
        }
        parts.append("Test case: " + json.dumps(snapshot, ensure_ascii=False)[:6000])
    parts.append(
        "Use browser_assert_text, browser_assert_visible, browser_assert_url, or "
        "browser_assert_network for explicit assertions. Navigation and clicks do not pass the test."
    )
    return "\n".join(part for part in parts if part)


class PlaywrightMCPWorker:
    """Owns the stdio process for one task and exposes the assertion proxy."""

    def __init__(
        self,
        *,
        package_ref: str,
        allowed_origin: str,
        workspace: str,
        command: str = "node",
        transport_factory: Callable[..., Any] = build_playwright_mcp_transport,
        client_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self.package_ref = package_ref
        self.allowed_origin = allowed_origin
        self.workspace = workspace
        self.command = command
        self.transport_factory = transport_factory
        self.client_factory = client_factory or (
            lambda transport: AutomationMCPClient(transport, allowed_tools=set(PLAYWRIGHT_SAFE_TOOLS))
        )
        self.transport: Any = None
        self._stopped = False

    async def start(self) -> PlaywrightAssertionProxy:
        self.transport = self.transport_factory(
            package_ref=self.package_ref,
            allowed_origin=self.allowed_origin,
            workspace=self.workspace,
            command=self.command,
        )
        proxy = PlaywrightAssertionProxy(
            self.client_factory(self.transport),
            allowed_origin=self.allowed_origin,
        )
        try:
            await proxy.health()
        except Exception:
            await self.stop()
            raise
        return proxy

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        transport = self.transport
        self.transport = None
        disconnect = getattr(transport, "disconnect", None)
        if disconnect is None:
            return
        result = disconnect()
        if hasattr(result, "__await__"):
            await result

    async def __aenter__(self) -> PlaywrightAssertionProxy:
        return await self.start()

    async def __aexit__(self, *_args: Any) -> bool:
        await self.stop()
        return False


def _terminal(status: str, code: str, message: str, *, retryable: bool = False) -> AgentRuntimeResult:
    return AgentRuntimeResult(status, None, error={"code": code, "message": message, "retryable": retryable})


async def run_web_ai_task(
    protocol: Any,
    lease: RunnerLease,
    *,
    workspace: str,
    completion: Callable[..., Any],
    db: Any = None,
    package_ref: str | None = None,
    worker_factory: Callable[..., PlaywrightMCPWorker] = PlaywrightMCPWorker,
    runtime_factory: Callable[..., AutomationAgentRuntime] = AutomationAgentRuntime,
) -> AgentRuntimeResult:
    """Run one Web AI task and always stop the MCP process before reporting."""
    task = lease.task
    if task.get("execution_mode") not in (None, "ai"):
        result = _terminal("blocked", "unsupported_mode", "The Playwright MCP worker only executes AI mode")
        await protocol.report(lease, result)
        return result
    try:
        origin = resolve_web_ai_origin(lease.context)
        package = resolve_playwright_package(task, package_ref)
    except ValueError as exc:
        result = _terminal("blocked", "blocked", str(exc))
        await protocol.report(lease, result)
        return result

    worker = worker_factory(package_ref=package, allowed_origin=origin, workspace=workspace)
    started = False
    try:
        proxy = await worker.start()
        started = True

        async def cancellation_check() -> bool:
            status = await protocol.heartbeat(lease)
            return bool(status.get("cancel_requested"))

        runtime = runtime_factory(
            db if db is not None else SimpleNamespace(),
            proxy,
            project_id=int(task["project_id"]),
            user_id=int(task["requested_by"]),
            max_steps=int(task.get("max_steps") or 50),
            timeout_seconds=int(task.get("timeout_seconds") or 900),
            token_budget=task.get("token_budget"),
            completion=completion,
            cancellation_check=cancellation_check,
            step_callback=protocol.evidence_sink(lease),
        )
        result = await runtime.run(build_web_ai_goal(lease))
    except ValueError as exc:
        result = _terminal(
            "blocked" if not started else "failed",
            "blocked" if not started else "worker_error",
            str(exc) if not started else "Playwright MCP worker failed during execution",
        )
    except Exception:
        result = _terminal(
            "failed" if started else "blocked",
            "worker_error" if started else "worker_unavailable",
            "Playwright MCP worker failed during execution" if started else "Playwright MCP worker failed to start",
            retryable=not started,
        )
    finally:
        await worker.stop()
    await protocol.report(lease, result)
    return result
