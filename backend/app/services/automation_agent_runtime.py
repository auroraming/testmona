"""Budgeted Agent Runtime for AI automation tasks."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from json_repair import repair_json
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from .ai_manager import AICompletionRequest, AICompletionResult, generate_ai_completion
from .automation_mcp_client import AutomationMCPClient, AutomationMCPError, AutomationMCPTool


class AgentDecision(BaseModel):
    type: str
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = Field(None, max_length=4000)

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"tool", "finish"}:
            raise ValueError("type must be tool or finish")
        return normalized


class AgentRuntimeError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass
class AgentStep:
    sequence: int
    tool: str
    arguments: dict[str, Any]
    output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


@dataclass
class AgentRuntimeResult:
    status: str
    summary: str | None
    steps: list[AgentStep] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    error: dict[str, Any] | None = None


CompletionFunction = Callable[..., Awaitable[AICompletionResult]]
CancellationCheck = Callable[[], Awaitable[bool]]


class AutomationAgentRuntime:
    """Runs an LLM decision loop without granting tools outside the MCP ACL."""

    def __init__(
        self,
        db: Session,
        mcp_client: AutomationMCPClient,
        *,
        project_id: int,
        user_id: int,
        max_steps: int,
        timeout_seconds: int,
        token_budget: int | None = None,
        completion: CompletionFunction = generate_ai_completion,
        cancellation_check: CancellationCheck | None = None,
    ) -> None:
        self.db = db
        self.mcp_client = mcp_client
        self.project_id = project_id
        self.user_id = user_id
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.token_budget = token_budget
        self.completion = completion
        self.cancellation_check = cancellation_check

    @staticmethod
    def _tool_catalog(tools: list[AutomationMCPTool]) -> list[dict[str, Any]]:
        return [
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
            for tool in tools
        ]

    @staticmethod
    def _parse_decision(content: str) -> AgentDecision:
        try:
            data = json.loads(repair_json(content))
            decision = AgentDecision.model_validate(data)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            raise AgentRuntimeError("invalid_model_output", "AI returned an invalid agent decision") from exc
        if decision.type == "tool" and not decision.tool:
            raise AgentRuntimeError("invalid_model_output", "Tool decisions must name a tool")
        return decision

    async def _is_cancelled(self) -> bool:
        return bool(self.cancellation_check and await self.cancellation_check())

    def _prompt(
        self,
        goal: str,
        tools: list[AutomationMCPTool],
        steps: list[AgentStep],
    ) -> str:
        history = [
            {
                "sequence": step.sequence,
                "tool": step.tool,
                "arguments": step.arguments,
                "output": step.output,
                "error": step.error,
            }
            for step in steps
        ]
        return (
            "You are TestMona's constrained test automation agent. Choose exactly one next action. "
            "Return JSON only: either {\"type\":\"tool\",\"tool\":\"name\",\"arguments\":{...}} "
            "or {\"type\":\"finish\",\"summary\":\"...\"}. Never claim success merely because a "
            "tool ran; assertions must be explicit tool results.\n"
            f"Goal: {goal}\nAllowed tools: {json.dumps(self._tool_catalog(tools), ensure_ascii=False)}\n"
            f"Completed steps: {json.dumps(history, ensure_ascii=False)}"
        )

    async def run(self, goal: str) -> AgentRuntimeResult:
        started = time.monotonic()
        steps: list[AgentStep] = []
        input_tokens = 0
        output_tokens = 0
        try:
            await self.mcp_client.health()
            tools = await self.mcp_client.discover_tools()
            if not tools:
                raise AgentRuntimeError("no_tools", "No authorized MCP tools are available")

            for _ in range(self.max_steps):
                if await self._is_cancelled():
                    return AgentRuntimeResult("cancelled", None, steps, input_tokens, output_tokens)
                remaining = self.timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise AgentRuntimeError("timeout", "Agent Runtime exceeded its task timeout", retryable=True)
                if self.token_budget is not None and input_tokens + output_tokens >= self.token_budget:
                    raise AgentRuntimeError("token_budget_exceeded", "Agent Runtime exhausted its token budget")

                max_tokens = 800
                if self.token_budget is not None:
                    max_tokens = max(1, min(max_tokens, self.token_budget - input_tokens - output_tokens))
                completion = await asyncio.wait_for(
                    self.completion(
                        self.db,
                        AICompletionRequest(
                            prompt=self._prompt(goal, tools, steps),
                            max_tokens=max_tokens,
                            temperature=0,
                            timeout_seconds=max(5, min(300, int(remaining))),
                        ),
                        operation="automation_agent",
                        project_id=self.project_id,
                        user_id=self.user_id,
                    ),
                    timeout=remaining,
                )
                input_tokens += completion.prompt_tokens
                output_tokens += completion.completion_tokens
                if self.token_budget is not None and input_tokens + output_tokens > self.token_budget:
                    raise AgentRuntimeError("token_budget_exceeded", "AI response exceeded the task token budget")

                decision = self._parse_decision(completion.content)
                if decision.type == "finish":
                    return AgentRuntimeResult("completed", decision.summary, steps, input_tokens, output_tokens)

                step = AgentStep(len(steps) + 1, decision.tool or "", decision.arguments)
                try:
                    step.output = await self.mcp_client.call_tool(step.tool, step.arguments)
                except AutomationMCPError as exc:
                    step.error = exc.as_dict()
                    if not exc.retryable:
                        steps.append(step)
                        raise AgentRuntimeError(exc.code, exc.message, retryable=False) from exc
                steps.append(step)

            raise AgentRuntimeError("max_steps_exceeded", "Agent Runtime reached the maximum number of steps")
        except asyncio.TimeoutError as exc:
            error = AgentRuntimeError("timeout", "Agent Runtime exceeded its task timeout", retryable=True)
            return AgentRuntimeResult("failed", None, steps, input_tokens, output_tokens, error.as_dict())
        except (AgentRuntimeError, AutomationMCPError) as exc:
            wrapped = exc if isinstance(exc, AgentRuntimeError) else AgentRuntimeError(exc.code, exc.message, retryable=exc.retryable)
            return AgentRuntimeResult("failed", None, steps, input_tokens, output_tokens, wrapped.as_dict())
