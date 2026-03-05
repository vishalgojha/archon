"""Tests for approval-gated EmailAgent outbound behavior."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field

import pytest

from archon.agents.outbound.email_agent import (
    EmailAgent,
    EmailSendResult,
    OutboundEmail,
    SMTPEmailTransport,
    build_email_transport_from_env,
)
from archon.config import ArchonConfig
from archon.core.approval_gate import ApprovalDeniedError, ApprovalGate
from archon.providers import ProviderRouter


@dataclass
class FakeEmailTransport:
    sent: list[OutboundEmail] = field(default_factory=list)

    async def send(self, message: OutboundEmail) -> EmailSendResult:
        self.sent.append(message)
        return EmailSendResult(provider="fake", message_id="fake-1", accepted=True, detail="ok")


def test_email_agent_sends_after_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    gate = ApprovalGate()
    transport = FakeEmailTransport()
    router = ProviderRouter(config=ArchonConfig(), live_mode=False)
    agent = EmailAgent(router=router, approval_gate=gate, transport=transport)

    events: list[dict[str, object]] = []

    async def sink(event: dict[str, object]) -> None:
        events.append(event)
        if event["type"] == "approval_required":
            gate.approve(str(event["request_id"]), approver="operator")

    async def _run():
        try:
            return await agent.send_email(
                task_id="task-1",
                to_email="lead@example.com",
                subject="Quick follow-up",
                body="Would you like a demo?",
                event_sink=sink,
            )
        finally:
            await router.aclose()

    result = asyncio.run(_run())
    assert result.agent == "EmailAgent"
    assert result.metadata["provider"] == "fake"
    assert len(transport.sent) == 1
    assert events and events[0]["type"] == "approval_required"


def test_email_agent_does_not_send_when_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    gate = ApprovalGate()
    transport = FakeEmailTransport()
    router = ProviderRouter(config=ArchonConfig(), live_mode=False)
    agent = EmailAgent(router=router, approval_gate=gate, transport=transport)

    async def sink(event: dict[str, object]) -> None:
        if event["type"] == "approval_required":
            gate.deny(str(event["request_id"]), approver="operator")

    async def _run():
        try:
            with pytest.raises(ApprovalDeniedError):
                await agent.send_email(
                    task_id="task-1",
                    to_email="lead@example.com",
                    subject="Quick follow-up",
                    body="Would you like a demo?",
                    event_sink=sink,
                )
        finally:
            await router.aclose()

    asyncio.run(_run())
    assert transport.sent == []


def test_build_email_transport_from_env_uses_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("ARCHON_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("ARCHON_SMTP_PORT", "587")
    monkeypatch.setenv("ARCHON_EMAIL_FROM", "noreply@example.com")
    monkeypatch.setenv("ARCHON_SMTP_USERNAME", "user")
    monkeypatch.setenv("ARCHON_SMTP_PASSWORD", "pass")

    transport = build_email_transport_from_env()
    assert isinstance(transport, SMTPEmailTransport)


def test_build_email_transport_from_env_without_required_fields_returns_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARCHON_EMAIL_PROVIDER", "smtp")
    monkeypatch.delenv("ARCHON_SMTP_HOST", raising=False)
    monkeypatch.delenv("ARCHON_EMAIL_FROM", raising=False)

    transport = build_email_transport_from_env()
    assert transport.__class__.__name__ == "NullEmailTransport"


def test_build_email_transport_from_env_sendgrid_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARCHON_EMAIL_PROVIDER", "sendgrid")
    monkeypatch.setenv("ARCHON_EMAIL_FROM", "noreply@example.com")
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)

    transport = build_email_transport_from_env()
    assert transport.__class__.__name__ == "NullEmailTransport"
    monkeypatch.delenv("ARCHON_EMAIL_PROVIDER", raising=False)
    monkeypatch.delenv("ARCHON_EMAIL_FROM", raising=False)
    monkeypatch.delenv("ARCHON_SMTP_USERNAME", raising=False)
    monkeypatch.delenv("ARCHON_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("ARCHON_SMTP_PORT", raising=False)
    monkeypatch.delenv("ARCHON_SMTP_HOST", raising=False)
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    os.environ.pop("ARCHON_SMTP_USE_TLS", None)
    os.environ.pop("ARCHON_SMTP_USE_STARTTLS", None)
