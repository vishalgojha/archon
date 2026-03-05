"""Tests for approval-gated WebChatAgent outbound behavior."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from archon.agents.outbound.webchat_agent import (
    WebChatAgent,
    WebChatMessage,
    WebChatSendResult,
    WebhookWebChatTransport,
    build_webchat_transport_from_env,
)
from archon.config import ArchonConfig
from archon.core.approval_gate import ApprovalDeniedError, ApprovalGate
from archon.providers import ProviderRouter


@dataclass
class FakeWebChatTransport:
    sent: list[WebChatMessage] = field(default_factory=list)

    async def send(self, message: WebChatMessage) -> WebChatSendResult:
        self.sent.append(message)
        return WebChatSendResult(
            provider="fake", message_id="fake-webchat-1", accepted=True, detail="ok"
        )


def test_webchat_agent_sends_after_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    gate = ApprovalGate()
    transport = FakeWebChatTransport()
    router = ProviderRouter(config=ArchonConfig(), live_mode=False)
    agent = WebChatAgent(router=router, approval_gate=gate, transport=transport)

    events: list[dict[str, object]] = []

    async def sink(event: dict[str, object]) -> None:
        events.append(event)
        if event["type"] == "approval_required":
            gate.approve(str(event["request_id"]), approver="operator")

    async def _run():
        try:
            return await agent.send_message(
                task_id="task-1",
                session_id="session-abc",
                text="Hi! Need help with setup?",
                event_sink=sink,
            )
        finally:
            await router.aclose()

    result = asyncio.run(_run())
    assert result.agent == "WebChatAgent"
    assert result.metadata["provider"] == "fake"
    assert len(transport.sent) == 1
    assert events and events[0]["type"] == "approval_required"


def test_webchat_agent_does_not_send_when_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    gate = ApprovalGate()
    transport = FakeWebChatTransport()
    router = ProviderRouter(config=ArchonConfig(), live_mode=False)
    agent = WebChatAgent(router=router, approval_gate=gate, transport=transport)

    async def sink(event: dict[str, object]) -> None:
        if event["type"] == "approval_required":
            gate.deny(str(event["request_id"]), approver="operator")

    async def _run():
        try:
            with pytest.raises(ApprovalDeniedError):
                await agent.send_message(
                    task_id="task-1",
                    session_id="session-abc",
                    text="Hi! Need help with setup?",
                    event_sink=sink,
                )
        finally:
            await router.aclose()

    asyncio.run(_run())
    assert transport.sent == []


def test_build_webchat_transport_from_env_uses_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_WEBCHAT_PROVIDER", "webhook")
    monkeypatch.setenv("ARCHON_WEBCHAT_WEBHOOK_URL", "https://example.com/webchat")
    monkeypatch.setenv("ARCHON_WEBCHAT_BEARER_TOKEN", "token")

    transport = build_webchat_transport_from_env()
    assert isinstance(transport, WebhookWebChatTransport)


def test_build_webchat_transport_from_env_without_url_returns_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARCHON_WEBCHAT_PROVIDER", "webhook")
    monkeypatch.delenv("ARCHON_WEBCHAT_WEBHOOK_URL", raising=False)

    transport = build_webchat_transport_from_env()
    assert transport.__class__.__name__ == "NullWebChatTransport"
