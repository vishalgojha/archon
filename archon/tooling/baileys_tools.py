"""Baileys-backed WhatsApp tools for the interactive chat agent."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from archon.tooling.base import BaseTool, ToolResult
from archon.whatsapp_native import get_whatsapp_client, native_whatsapp_enabled


@dataclass(slots=True)
class BaileysStatusTool(BaseTool):
    """Check whether the configured WhatsApp transport is reachable."""

    context: dict[str, Any] = field(default_factory=dict)
    name: str = "baileys_status"
    description: str = "Check whether the configured Baileys WhatsApp gateway is online."
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )

    async def execute(self, **kwargs) -> ToolResult:
        del kwargs
        try:
            payload = await get_whatsapp_client().status()
        except Exception as exc:
            return ToolResult(ok=False, output=f"Baileys status check failed: {exc}")
        body = json.dumps(payload, ensure_ascii=False)
        return ToolResult(
            ok=bool(payload.get("ok", False)),
            output=body,
            metadata={"native": native_whatsapp_enabled()},
        )


@dataclass(slots=True)
class BaileysSendMessageTool(BaseTool):
    """Send a WhatsApp message through the configured WhatsApp transport."""

    context: dict[str, Any] = field(default_factory=dict)
    name: str = "baileys_send_message"
    description: str = "Send a WhatsApp message through the configured Baileys gateway."
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "WhatsApp JID or chat id. Defaults to the current sender when available.",
                },
                "text": {
                    "type": "string",
                    "description": "Message text to send.",
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        }
    )

    async def execute(self, **kwargs) -> ToolResult:
        chat_id = str(kwargs.get("chat_id") or self.context.get("sender_id") or "").strip()
        text = str(kwargs.get("text") or "").strip()
        if not chat_id:
            return ToolResult(ok=False, output="chat_id is required")
        if not text:
            return ToolResult(ok=False, output="text is required")

        try:
            payload = await get_whatsapp_client().send_message(chat_id=chat_id, text=text)
        except Exception as exc:
            return ToolResult(ok=False, output=f"Baileys send failed: {exc}")
        body = json.dumps(payload, ensure_ascii=False)
        return ToolResult(
            ok=bool(payload.get("ok", False)),
            output=body,
            metadata={"chat_id": chat_id, "native": native_whatsapp_enabled()},
        )
