"""Webchat outbound integration with approval-gated execution."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.core.approval_gate import ApprovalDecision, ApprovalGate
from archon.providers import ProviderRouter


@dataclass(slots=True)
class WebChatMessage:
    """Outbound webchat message payload."""

    session_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WebChatSendResult:
    """Normalized outbound webchat send result."""

    provider: str
    message_id: str
    accepted: bool
    detail: str = ""


class WebChatTransport(Protocol):
    """Transport contract for outbound webchat messages."""

    async def send(self, message: WebChatMessage) -> WebChatSendResult:
        """Send one webchat message."""


@dataclass(slots=True)
class WebhookWebChatConfig:
    """Webhook transport configuration."""

    endpoint_url: str
    bearer_token: str | None = None
    timeout_seconds: float = 10.0


class WebhookWebChatTransport:
    """HTTP webhook transport for webchat message delivery."""

    def __init__(self, config: WebhookWebChatConfig) -> None:
        self.config = config

    async def send(self, message: WebChatMessage) -> WebChatSendResult:
        headers = {"Content-Type": "application/json"}
        if self.config.bearer_token:
            headers["Authorization"] = f"Bearer {self.config.bearer_token}"
        payload = {
            "session_id": message.session_id,
            "text": message.text,
            "metadata": message.metadata,
        }
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post(self.config.endpoint_url, json=payload, headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Webchat webhook send failed with HTTP {response.status_code}: {response.text}"
            )
        message_id = response.headers.get("x-message-id") or f"webchat-{uuid.uuid4().hex[:12]}"
        return WebChatSendResult(
            provider="webhook",
            message_id=message_id,
            accepted=True,
            detail="Webhook accepted message.",
        )


class NullWebChatTransport:
    """No-op transport that fails fast when webchat is not configured."""

    async def send(self, message: WebChatMessage) -> WebChatSendResult:
        del message
        raise RuntimeError(
            "Webchat transport not configured. Set ARCHON_WEBCHAT_PROVIDER and required settings."
        )


class WebChatAgent(BaseAgent):
    """Outbound webchat agent guarded by human approval."""

    role = "fast"

    def __init__(
        self,
        router: ProviderRouter,
        approval_gate: ApprovalGate,
        transport: WebChatTransport | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(router, name=name or "WebChatAgent")
        self.approval_gate = approval_gate
        self.transport = transport or build_webchat_transport_from_env()

    async def send_message(
        self,
        *,
        task_id: str,
        session_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        event_sink=None,
    ) -> AgentResult:
        """Send one approval-gated outbound webchat message."""

        message = WebChatMessage(session_id=session_id, text=text, metadata=metadata or {})
        approval_payload = {
            "task_id": task_id,
            "channel": "webchat",
            "session_id": session_id,
            "text_preview": text[:160],
            "metadata": message.metadata,
        }
        decision: ApprovalDecision = await self.approval_gate.guard(
            action_type="outbound_webchat",
            payload=approval_payload,
            event_sink=event_sink,
        )

        send_result = await self.transport.send(message)
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=f"Webchat message sent to session {session_id}.",
            confidence=95,
            metadata={
                "task_id": task_id,
                "channel": "webchat",
                "provider": send_result.provider,
                "message_id": send_result.message_id,
                "accepted": send_result.accepted,
                "detail": send_result.detail,
                "approval": decision.to_event_payload(),
                "metadata": message.metadata,
            },
        )

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Execute default webchat action from context payload."""

        del goal
        return await self.send_message(
            task_id=task_id,
            session_id=str(context["session_id"]),
            text=str(context["text"]),
            metadata=context.get("metadata") if isinstance(context.get("metadata"), dict) else None,
            event_sink=context.get("event_sink"),
        )


def build_webchat_transport_from_env() -> WebChatTransport:
    """Build configured webchat transport from environment variables."""

    provider = os.getenv("ARCHON_WEBCHAT_PROVIDER", "").strip().lower()
    if provider == "webhook":
        endpoint_url = os.getenv("ARCHON_WEBCHAT_WEBHOOK_URL", "").strip()
        if not endpoint_url:
            return NullWebChatTransport()
        return WebhookWebChatTransport(
            WebhookWebChatConfig(
                endpoint_url=endpoint_url,
                bearer_token=os.getenv("ARCHON_WEBCHAT_BEARER_TOKEN") or None,
            )
        )
    return NullWebChatTransport()
