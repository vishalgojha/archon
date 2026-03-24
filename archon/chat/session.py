"""Persistent interactive chat sessions with provider-native tool calling."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from archon.config import ArchonConfig
from archon.providers import ProviderRouter
from archon.providers.types import ProviderToolCall, ProviderToolResponse
from archon.tooling import ToolRegistry, ToolResult, build_default_tool_registry

ChatEventSink = Callable[[dict[str, Any]], Awaitable[None] | None]


def _render_tool_result(result: ToolResult) -> str:
    if result.ok and not result.metadata:
        return result.output
    payload: dict[str, Any] = {"ok": result.ok, "output": result.output}
    if result.metadata:
        payload["metadata"] = result.metadata
    return json.dumps(payload, ensure_ascii=False)


def _openai_tool_calls(calls: list[ProviderToolCall]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for call in calls:
        rendered.append(
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
        )
    return rendered


@dataclass(slots=True)
class ChatResult:
    turn_id: str
    reply: str
    provider: str
    model: str
    steps: int
    cost_usd: float = 0.0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class ChatSession:
    """Persistent chat session that preserves conversation history across turns."""

    def __init__(
        self,
        *,
        router: ProviderRouter,
        tools: ToolRegistry,
        role: str = "primary",
        system_prompt: str | None = None,
        context: dict[str, Any] | None = None,
        max_steps: int = 8,
        session_id: str | None = None,
    ) -> None:
        self.router = router
        self.tools = tools
        self.role = role
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.context = dict(context or {})
        self.session_id = session_id or f"chat-{uuid.uuid4().hex[:10]}"
        self._events: list[dict[str, Any]] = []

    async def send(
        self,
        *,
        message: str,
        event_sink: ChatEventSink | None = None,
    ) -> ChatResult:
        text = str(message).strip()
        if not text:
            raise ValueError("message is required")

        turn_id = f"{self.session_id}-turn-{len(self._events) + 1}"
        self._events.append({"type": "user", "content": text})
        await self._emit(
            event_sink,
            {
                "type": "turn_started",
                "turn_id": turn_id,
                "message": text,
            },
        )

        total_cost = 0.0
        tool_call_log: list[dict[str, Any]] = []
        provider_name = ""
        model_name = ""

        for step in range(1, self.max_steps + 1):
            provider_style = self._provider_style()
            response = await self.router.invoke_with_tools(
                role=self.role,
                messages=self._build_messages(provider_style),
                tools=self._tool_schema(provider_style),
                task_id=turn_id,
                system_prompt=self.system_prompt if provider_style == "anthropic" else None,
                tool_style=provider_style,
            )
            provider_name = response.provider
            model_name = response.model
            total_cost += float(response.usage.cost_usd)

            if response.tool_calls:
                self._append_tool_call_event(response)
                for call in response.tool_calls:
                    await self._emit(
                        event_sink,
                        {
                            "type": "tool_call",
                            "turn_id": turn_id,
                            "name": call.name,
                            "arguments": call.arguments,
                            "step": step,
                        },
                    )
                    result = await self._execute_tool(call)
                    tool_call_log.append(
                        {
                            "name": call.name,
                            "arguments": call.arguments,
                            "ok": result.ok,
                        }
                    )
                    self._events.append(
                        {
                            "type": "tool_result",
                            "call_id": call.call_id,
                            "name": call.name,
                            "content": _render_tool_result(result),
                            "is_error": not result.ok,
                        }
                    )
                    await self._emit(
                        event_sink,
                        {
                            "type": "tool_result",
                            "turn_id": turn_id,
                            "name": call.name,
                            "ok": result.ok,
                            "output": result.output,
                            "step": step,
                        },
                    )
                continue

            reply = (response.text or "").strip()
            self._events.append({"type": "assistant", "content": reply})
            await self._emit(
                event_sink,
                {
                    "type": "turn_completed",
                    "turn_id": turn_id,
                    "reply": reply,
                    "provider": provider_name,
                    "model": model_name,
                    "steps": step,
                    "cost_usd": total_cost,
                },
            )
            return ChatResult(
                turn_id=turn_id,
                reply=reply,
                provider=provider_name,
                model=model_name,
                steps=step,
                cost_usd=total_cost,
                tool_calls=tool_call_log,
            )

        reply = "I hit the tool-calling step limit before I could finish the reply."
        self._events.append({"type": "assistant", "content": reply})
        return ChatResult(
            turn_id=turn_id,
            reply=reply,
            provider=provider_name,
            model=model_name,
            steps=self.max_steps,
            cost_usd=total_cost,
            tool_calls=tool_call_log,
        )

    def history(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events]

    def _provider_style(self) -> str:
        selection = self.router.resolve_provider(self.role)
        return "anthropic" if selection.provider == "anthropic" else "openai"

    def _tool_schema(self, provider_style: str) -> list[dict[str, Any]]:
        if provider_style == "anthropic":
            return self.tools.anthropic_schema()
        return self.tools.openai_schema()

    def _build_messages(self, provider_style: str) -> list[dict[str, Any]]:
        if provider_style == "anthropic":
            return self._build_anthropic_messages()
        return self._build_openai_messages()

    def _build_openai_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        for event in self._events:
            event_type = str(event.get("type"))
            if event_type == "user":
                messages.append({"role": "user", "content": event.get("content", "")})
            elif event_type == "assistant":
                messages.append({"role": "assistant", "content": event.get("content", "")})
            elif event_type == "assistant_tool_calls":
                messages.append(
                    {
                        "role": "assistant",
                        "content": event.get("text", ""),
                        "tool_calls": _openai_tool_calls(event.get("calls", [])),
                    }
                )
            elif event_type == "tool_result":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": event.get("call_id", ""),
                        "content": event.get("content", ""),
                    }
                )
        return messages

    def _build_anthropic_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        pending_user_blocks: list[dict[str, Any]] = []

        def flush_user_blocks() -> None:
            nonlocal pending_user_blocks
            if pending_user_blocks:
                messages.append({"role": "user", "content": list(pending_user_blocks)})
                pending_user_blocks = []

        for event in self._events:
            event_type = str(event.get("type"))
            if event_type == "user":
                flush_user_blocks()
                pending_user_blocks.append({"type": "text", "text": event.get("content", "")})
                flush_user_blocks()
            elif event_type == "assistant":
                flush_user_blocks()
                messages.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": event.get("content", "")}],
                    }
                )
            elif event_type == "assistant_tool_calls":
                flush_user_blocks()
                content: list[dict[str, Any]] = []
                text = str(event.get("text", "")).strip()
                if text:
                    content.append({"type": "text", "text": text})
                for call in event.get("calls", []):
                    content.append(
                        {
                            "type": "tool_use",
                            "id": call.call_id,
                            "name": call.name,
                            "input": call.arguments,
                        }
                    )
                messages.append({"role": "assistant", "content": content})
            elif event_type == "tool_result":
                pending_user_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": event.get("call_id", ""),
                        "content": event.get("content", ""),
                        "is_error": bool(event.get("is_error", False)),
                    }
                )
        flush_user_blocks()
        return messages

    def _append_tool_call_event(self, response: ProviderToolResponse) -> None:
        self._events.append(
            {
                "type": "assistant_tool_calls",
                "text": response.text or "",
                "calls": list(response.tool_calls),
            }
        )

    async def _execute_tool(self, call: ProviderToolCall) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(ok=False, output=f"Unknown tool: {call.name}")
        try:
            return await tool.execute(**call.arguments)
        except Exception as exc:
            return ToolResult(ok=False, output=str(exc))

    async def _emit(self, sink: ChatEventSink | None, event: dict[str, Any]) -> None:
        if sink is None:
            return
        maybe_awaitable = sink(event)
        if maybe_awaitable is not None:
            await maybe_awaitable


@dataclass(slots=True)
class ChatRuntime:
    """Shared runtime for creating multiple interactive chat sessions."""

    router: ProviderRouter
    tools: ToolRegistry
    role: str = "primary"
    system_prompt: str | None = None
    max_steps: int = 8

    def new_session(
        self,
        *,
        context: dict[str, Any] | None = None,
        system_prompt: str | None = None,
        session_id: str | None = None,
    ) -> ChatSession:
        return ChatSession(
            router=self.router,
            tools=self.tools if not context else build_default_tool_registry(context=context),
            role=self.role,
            system_prompt=system_prompt or self.system_prompt,
            context=context,
            max_steps=self.max_steps,
            session_id=session_id,
        )

    async def aclose(self) -> None:
        await self.router.aclose()


def build_chat_runtime(
    *,
    config: ArchonConfig,
    context: dict[str, Any] | None = None,
    system_prompt: str | None = None,
    role: str = "primary",
    max_steps: int = 8,
) -> ChatRuntime:
    router = ProviderRouter(config)
    tools = build_default_tool_registry(context=context)
    return ChatRuntime(
        router=router,
        tools=tools,
        role=role,
        system_prompt=system_prompt,
        max_steps=max_steps,
    )
