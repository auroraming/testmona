"""Restricted MCP client used by the AI automation Agent Runtime.

The wrapper deliberately requires a per-task tool allowlist.  It discovers the
remote schemas before every uncached call, validates arguments locally, and
normalizes transport/protocol failures so the Agent Runtime never receives a
raw client exception or gains access to an unapproved tool.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from fastmcp import Client
from jsonschema import SchemaError, ValidationError, validate


class AutomationMCPError(Exception):
    """Structured MCP failure safe to persist as an automation error."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True)
class AutomationMCPTool:
    name: str
    description: str | None
    input_schema: dict[str, Any]


class AutomationMCPClient:
    """MCP transport facade with discovery, validation, timeout, and ACLs."""

    def __init__(
        self,
        transport: Any,
        *,
        allowed_tools: set[str] | frozenset[str],
        timeout_seconds: float = 30,
        client_factory: Callable[..., Any] = Client,
    ) -> None:
        if not allowed_tools:
            raise ValueError("allowed_tools cannot be empty")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be between 0 and 300")
        self.transport = transport
        self.allowed_tools = frozenset(allowed_tools)
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory

    async def _run(self, operation: Callable[[Any], Any]) -> Any:
        try:
            async with self.client_factory(self.transport, timeout=self.timeout_seconds) as client:
                return await asyncio.wait_for(operation(client), timeout=self.timeout_seconds)
        except AutomationMCPError:
            raise
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise AutomationMCPError("timeout", "MCP operation timed out", retryable=True) from exc
        except Exception as exc:
            raise AutomationMCPError(
                "transport_error",
                f"MCP service is unavailable: {type(exc).__name__}",
                retryable=True,
            ) from exc

    async def health(self) -> bool:
        async def ping(client: Any) -> bool:
            return bool(await client.ping())

        result = await self._run(ping)
        if not result:
            raise AutomationMCPError("unhealthy", "MCP service did not acknowledge ping", retryable=True)
        return True

    async def discover_tools(self) -> list[AutomationMCPTool]:
        async def discover(client: Any) -> list[Any]:
            return await client.list_tools()

        tools = await self._run(discover)
        return [
            AutomationMCPTool(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema or {"type": "object"},
            )
            for tool in tools
            if tool.name in self.allowed_tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in self.allowed_tools:
            raise AutomationMCPError("tool_forbidden", f"Tool '{name}' is not authorized for this task")

        discovered = {tool.name: tool for tool in await self.discover_tools()}
        tool = discovered.get(name)
        if tool is None:
            raise AutomationMCPError("tool_not_found", f"Authorized tool '{name}' is not available")

        payload = arguments or {}
        try:
            validate(instance=payload, schema=tool.input_schema)
        except ValidationError as exc:
            path = ".".join(str(item) for item in exc.absolute_path) or "arguments"
            raise AutomationMCPError("invalid_arguments", f"Invalid {path}: {exc.message}") from exc
        except SchemaError as exc:
            raise AutomationMCPError("invalid_tool_schema", f"Tool '{name}' published an invalid schema") from exc

        async def invoke(client: Any) -> Any:
            return await client.call_tool(name, payload, timeout=self.timeout_seconds, raise_on_error=False)

        result = await self._run(invoke)
        if result.is_error:
            raise AutomationMCPError("tool_error", f"Tool '{name}' returned an error", retryable=False)
        return {
            "structured_content": result.structured_content,
            "content": [item.model_dump(mode="json") for item in result.content],
        }
