"""WhatsApp interface layer for interactive ARCHON chat sessions."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from archon.chat import ChatRuntime, ChatSession, build_chat_runtime
from archon.config import load_archon_config
from archon.whatsapp_native import get_whatsapp_client, native_whatsapp_enabled

_INTERFACE_CACHE: dict[str, "WhatsAppInterface"] = {}


class WhatsAppInterface:
    """Minimal WhatsApp adapter for inbound/outbound chat wiring."""

    def __init__(self, *, config_path: str = "config.archon.yaml") -> None:
        self.config_path = config_path
        self.config = load_archon_config(config_path)
        self._runtime: ChatRuntime = build_chat_runtime(
            config=self.config,
            context={"channel": "whatsapp"},
            system_prompt=(
                "You are ARCHON handling a WhatsApp chat. Keep replies concise, helpful, "
                "and ready to send as WhatsApp messages. Use tools only when they move "
                "the conversation forward."
            ),
        )
        self._sessions: dict[str, ChatSession] = {}

    async def handle_inbound(self, *, goal: str, sender_id: str) -> list[str]:
        """Handle one inbound WhatsApp message and return outbound replies."""
        replies: list[str] = []
        if _should_send_ack():
            replies.append("Working on it. I will reply shortly.")
        session = self._sessions.get(sender_id)
        if session is None:
            session = self._runtime.new_session(
                context={"channel": "whatsapp", "sender_id": sender_id},
                session_id=f"whatsapp-{sender_id}",
            )
            self._sessions[sender_id] = session
        result = await session.send(message=goal)
        replies.append(_truncate_whatsapp(result.reply))
        return replies

    async def drain_native_inbox(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Process messages pulled directly from the native WhatsApp sidecar."""
        if not native_whatsapp_enabled():
            return []

        payload = await get_whatsapp_client().fetch_inbox(limit=limit)
        messages = list(payload.get("messages") or [])
        processed: list[dict[str, Any]] = []
        ack_ids: list[str] = []

        for item in messages:
            if not isinstance(item, dict):
                continue
            sender_id = str(item.get("sender_id") or item.get("chat_id") or "").strip()
            goal = str(item.get("text") or "").strip()
            if not sender_id or not goal:
                continue
            replies = await self.handle_inbound(goal=goal, sender_id=sender_id)
            processed.append(
                {
                    "message_id": item.get("message_id"),
                    "sender_id": sender_id,
                    "goal": goal,
                    "replies": replies,
                }
            )
            message_id = str(item.get("message_id") or "").strip()
            if message_id:
                ack_ids.append(message_id)

        if ack_ids:
            await get_whatsapp_client().ack_messages(message_ids=ack_ids)

        return processed

    async def aclose(self) -> None:
        await self._runtime.aclose()


def _should_send_ack() -> bool:
    return str(os.getenv("ARCHON_WHATSAPP_ACK", "on")).lower() in {"1", "true", "yes", "on"}


def _truncate_whatsapp(text: str, limit: int = 1000) -> str:
    trimmed = text.replace("**", "").replace("`", "").strip()
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[: limit - 3].rstrip() + "..."


async def handle_whatsapp_message(payload: dict[str, Any]) -> dict[str, Any]:
    """Convenience handler for webhook adapters."""
    goal = str(payload.get("message", "")).strip()
    sender = str(payload.get("sender", "unknown"))
    config_path = str(payload.get("config_path", "config.archon.yaml"))
    interface = _INTERFACE_CACHE.get(config_path)
    if interface is None:
        interface = WhatsAppInterface(config_path=config_path)
        _INTERFACE_CACHE[config_path] = interface
    replies = await interface.handle_inbound(goal=goal, sender_id=sender)
    return {"sender": sender, "replies": replies}


async def drain_native_whatsapp(
    *,
    config_path: str = "config.archon.yaml",
    limit: int = 20,
) -> list[dict[str, Any]]:
    interface = _INTERFACE_CACHE.get(config_path)
    if interface is None:
        interface = WhatsAppInterface(config_path=config_path)
        _INTERFACE_CACHE[config_path] = interface
    return await interface.drain_native_inbox(limit=limit)


def handle_whatsapp_message_sync(payload: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(handle_whatsapp_message(payload))
