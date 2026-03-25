"""Tool-calling loop for OpenAI and Claude styles."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from archon.providers import ProviderRouter
from archon.providers.types import ProviderToolCall
from archon.tooling.base import ToolResult
from archon.tooling.registry import ToolRegistry


@dataclass(slots=True)
class ToolRunResult:
    final_answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0


def _render_tool_result(result: ToolResult) -> str:
    if result.ok and not result.metadata:
        return result.output
    payload: dict[str, Any] = {"ok": result.ok, "output": result.output}
    if result.metadata:
        payload["metadata"] = result.metadata
    return json.dumps(payload, ensure_ascii=False)


class ToolCallingAgent:
    """Executes a tool-calling loop against the configured provider."""

    def __init__(
        self,
        router: ProviderRouter,
        tools: ToolRegistry,
        *,
        role: str = "primary",
        system_prompt: str | None = None,
        max_steps: int = 8,
    ) -> None:
        self.router = router
        self.tools = tools
        self.role = role
        self.system_prompt = system_prompt
        self.max_steps = max_steps

    async def run(self, *, goal: str, task_id: str) -> ToolRunResult:
        selection = self.router.resolve_provider(self.role)
        tool_style = "anthropic" if selection.provider == "anthropic" else "openai"
        if tool_style == "anthropic":
            return await self._run_anthropic(goal=goal, task_id=task_id)
        return await self._run_openai(goal=goal, task_id=task_id)

    async def _run_openai(self, *, goal: str, task_id: str) -> ToolRunResult:
        messages: list[dict[str, Any]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": goal})

        tools_schema = self.tools.openai_schema()
        tool_calls_log: list[dict[str, Any]] = []

        for step in range(self.max_steps):
            response = await self.router.invoke_with_tools(
                role=self.role,
                messages=messages,
                tools=tools_schema,
                task_id=task_id,
                tool_style="openai",
            )

            tool_calls = response.tool_calls
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": response.text or "",
            }
            if tool_calls:
                assistant_message["tool_calls"] = _openai_tool_calls(tool_calls)
            messages.append(assistant_message)

            if not tool_calls:
                return ToolRunResult(
                    final_answer=response.text or "", tool_calls=tool_calls_log, steps=step + 1
                )

            for call in tool_calls:
                result = await self._execute_tool(call)
                tool_calls_log.append(
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "ok": result.ok,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "content": _render_tool_result(result),
                    }
                )

        return ToolRunResult(
            final_answer="Reached tool-calling step limit without a final answer.",
            tool_calls=tool_calls_log,
            steps=self.max_steps,
        )

    async def _run_anthropic(self, *, goal: str, task_id: str) -> ToolRunResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": goal}]
        tools_schema = self.tools.anthropic_schema()
        tool_calls_log: list[dict[str, Any]] = []

        for step in range(self.max_steps):
            response = await self.router.invoke_with_tools(
                role=self.role,
                messages=messages,
                tools=tools_schema,
                task_id=task_id,
                system_prompt=self.system_prompt,
                tool_style="anthropic",
            )

            tool_calls = response.tool_calls
            assistant_blocks: list[dict[str, Any]] = []
            if response.text:
                assistant_blocks.append({"type": "text", "text": response.text})
            if tool_calls:
                for call in tool_calls:
                    assistant_blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.call_id,
                            "name": call.name,
                            "input": call.arguments,
                        }
                    )
            messages.append({"role": "assistant", "content": assistant_blocks})

            if not tool_calls:
                return ToolRunResult(
                    final_answer=response.text or "", tool_calls=tool_calls_log, steps=step + 1
                )

            tool_result_blocks: list[dict[str, Any]] = []
            for call in tool_calls:
                result = await self._execute_tool(call)
                tool_calls_log.append(
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "ok": result.ok,
                    }
                )
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.call_id,
                        "content": _render_tool_result(result),
                        "is_error": not result.ok,
                    }
                )
            messages.append({"role": "user", "content": tool_result_blocks})

        return ToolRunResult(
            final_answer="Reached tool-calling step limit without a final answer.",
            tool_calls=tool_calls_log,
            steps=self.max_steps,
        )

    async def _execute_tool(self, call: ProviderToolCall) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(ok=False, output=f"Unknown tool: {call.name}")
        try:
            return await tool.execute(**call.arguments)
        except Exception as exc:
            return ToolResult(ok=False, output=str(exc))


def _openai_tool_calls(calls: list[ProviderToolCall]) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for call in calls:
        tool_calls.append(
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
        )
    return tool_calls
