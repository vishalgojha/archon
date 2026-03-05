"""Tests for outreach EmailAgent, backends, and unsubscribe/personalization helpers."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from archon.agents.outreach.email_agent import (
    EmailAgent,
    EmailPayload,
    SMTPBackend,
    SendGridBackend,
    SendResult,
    UnsubscribeStore,
    personalize,
)
from archon.core.approval_gate import ApprovalGate


class _DummyRouter:
    pass


class _RecordingBackend:
    def __init__(self, *, status: str = "sent") -> None:
        self.status = status
        self.calls: list[EmailPayload] = []

    async def send(self, payload: EmailPayload) -> SendResult:
        self.calls.append(payload)
        if self.status == "sent":
            return SendResult(payload.to, "sent", "fake", message_id="fake-1")
        return SendResult(payload.to, "failed", "fake", error="forced failure")


def test_personalize_variants() -> None:
    assert personalize("Hi {{name}}", {"name": "Ava"}) == "Hi Ava"
    assert personalize("{{a}} + {{b}}", {"a": "1", "b": "2"}) == "1 + 2"
    assert personalize("Hi {{missing}}", {"name": "Ava"}) == "Hi {{missing}}"
    assert personalize("", {"name": "Ava"}) == ""
    assert personalize("{{x}}/{{x}}", {"x": "dup"}) == "dup/dup"
    assert personalize("Score {{n}}", {"n": 42}) == "Score 42"


def test_unsubscribe_store_case_insensitive_and_bulk() -> None:
    store = UnsubscribeStore()
    store.add("User@Example.com")
    assert store.is_unsubscribed("user@example.com") is True
    store.remove("USER@EXAMPLE.COM")
    assert store.is_unsubscribed("user@example.com") is False
    store.bulk_add(["a@example.com", "A@example.com", "b@example.com"])
    assert store.count == 2


@pytest.mark.asyncio
async def test_smtp_backend_success_with_mocked_aiosmtplib_and_mime_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_send(message, **kwargs):  # type: ignore[no-untyped-def]
        captured["message"] = message
        captured["kwargs"] = kwargs

    monkeypatch.setitem(sys.modules, "aiosmtplib", types.SimpleNamespace(send=fake_send))
    backend = SMTPBackend(
        host="smtp.example.com",
        port=587,
        user="user",
        password="pass",
        use_tls=False,
        from_address="from@example.com",
    )
    result = await backend.send(
        EmailPayload(
            to="to@example.com",
            subject="Hello",
            body_text="Plain text",
            body_html="<b>HTML</b>",
            reply_to="reply@example.com",
            cc=["cc1@example.com", "cc2@example.com"],
        )
    )

    assert result.status == "sent"
    msg = captured["message"]
    assert msg["Message-ID"]
    assert msg["Reply-To"] == "reply@example.com"
    assert msg["Cc"] == "cc1@example.com, cc2@example.com"
    assert msg.get_content_type() == "multipart/alternative"
    part_types = [part.get_content_type() for part in msg.walk()]
    assert "text/plain" in part_types
    assert "text/html" in part_types


@pytest.mark.asyncio
async def test_smtp_backend_failure_returns_failed_send_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_send(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("smtp failed")

    monkeypatch.setitem(sys.modules, "aiosmtplib", types.SimpleNamespace(send=fake_send))
    backend = SMTPBackend(host="smtp.example.com", port=587, from_address="from@example.com")
    result = await backend.send(EmailPayload(to="to@example.com", subject="Hi", body_text="Body"))

    assert result.status == "failed"
    assert result.error and "smtp failed" in result.error


class _FakeResponse:
    def __init__(self, status_code: int, *, text: str = "", headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class _FakeClient:
    response: _FakeResponse
    captured: dict[str, Any]

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        del args, kwargs

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        del exc_type, exc, tb

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        self.__class__.captured = {"url": url, "json": json, "headers": headers}
        return self.__class__.response


@pytest.mark.asyncio
async def test_sendgrid_backend_success_202(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.email_backends as email_module

    _FakeClient.response = _FakeResponse(202, headers={"X-Message-Id": "sg-123"})
    monkeypatch.setattr(email_module.httpx, "AsyncClient", _FakeClient)
    backend = SendGridBackend(api_key="api-key", from_address="from@example.com")
    result = await backend.send(EmailPayload(to="to@example.com", subject="Hi", body_text="Body"))

    assert result.status == "sent"
    assert result.message_id == "sg-123"
    assert _FakeClient.captured["url"] == "https://api.sendgrid.com/v3/mail/send"


@pytest.mark.asyncio
async def test_sendgrid_backend_auth_failure_401(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.email_backends as email_module

    _FakeClient.response = _FakeResponse(401, text="unauthorized")
    monkeypatch.setattr(email_module.httpx, "AsyncClient", _FakeClient)
    backend = SendGridBackend(api_key="bad", from_address="from@example.com")
    result = await backend.send(EmailPayload(to="to@example.com", subject="Hi", body_text="Body"))

    assert result.status == "failed"
    assert result.error and "401" in result.error


@pytest.mark.asyncio
async def test_sendgrid_backend_no_api_key_returns_failed() -> None:
    backend = SendGridBackend(api_key="", from_address="from@example.com")
    result = await backend.send(EmailPayload(to="to@example.com", subject="Hi", body_text="Body"))
    assert result.status == "failed"
    assert result.error and "SENDGRID_API_KEY" in result.error


@pytest.mark.asyncio
async def test_email_agent_send_success_personalization_and_footer() -> None:
    gate = ApprovalGate(default_timeout_seconds=1.0)
    backend = _RecordingBackend(status="sent")
    agent = EmailAgent(
        _DummyRouter(), gate, backend=backend, unsubscribe_url="https://example.com/unsub"
    )
    events: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        events.append(event)
        gate.approve(str(event["request_id"]), approver="tester", notes="ok")

    result = await agent.send(
        "lead@example.com",
        "Hi {{name}}",
        "Body for {{name}}",
        body_html="<p>Hello {{name}}</p>",
        context={"name": "Ava"},
        event_sink=sink,
    )

    assert result.status == "sent"
    assert len(events) == 1
    payload = backend.calls[0]
    assert payload.subject == "Hi Ava"
    assert payload.body_text.startswith("Body for Ava")
    assert "Unsubscribe:" in payload.body_text
    assert payload.body_html == "<p>Hello Ava</p>"

    result_no_footer = await agent.send(
        "lead2@example.com",
        "No Footer",
        "Body",
        context={},
        add_unsubscribe_footer=False,
        event_sink=sink,
    )
    assert result_no_footer.status == "sent"
    assert "Unsubscribe:" not in backend.calls[1].body_text


@pytest.mark.asyncio
async def test_email_agent_send_unsubscribed_blocked_before_gate() -> None:
    gate = ApprovalGate(default_timeout_seconds=1.0)
    backend = _RecordingBackend(status="sent")
    store = UnsubscribeStore()
    store.add("blocked@example.com")
    agent = EmailAgent(_DummyRouter(), gate, backend=backend, unsubscribe_store=store)

    events: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        events.append(event)

    result = await agent.send("BLOCKED@example.com", "Hi", "Body", event_sink=sink)

    assert result.status == "blocked:unsubscribed"
    assert len(backend.calls) == 0
    assert events == []


@pytest.mark.asyncio
async def test_email_agent_send_denied_without_backend_call() -> None:
    gate = ApprovalGate(default_timeout_seconds=1.0)
    backend = _RecordingBackend(status="sent")
    agent = EmailAgent(_DummyRouter(), gate, backend=backend)
    events: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        events.append(event)
        gate.deny(str(event["request_id"]), reason="policy")

    result = await agent.send(
        "lead@example.com",
        "Subject",
        "x" * 250,
        event_sink=sink,
    )

    assert result.status == "denied:policy"
    assert len(backend.calls) == 0
    assert len(events) == 1
    assert events[0]["action_type"] == "email_send"
    assert events[0]["context"]["to"] == "lead@example.com"
    assert events[0]["context"]["subject"] == "Subject"
    assert len(events[0]["context"]["body_preview"]) == 200


@pytest.mark.asyncio
async def test_email_agent_send_timeout_returns_failure() -> None:
    gate = ApprovalGate(default_timeout_seconds=0.01)
    backend = _RecordingBackend(status="sent")
    agent = EmailAgent(_DummyRouter(), gate, backend=backend)

    async def sink(event: dict[str, Any]) -> None:
        del event

    result = await agent.send("lead@example.com", "Subject", "Body", event_sink=sink)
    assert result.status.startswith("denied:")
    assert len(backend.calls) == 0


@pytest.mark.asyncio
async def test_email_agent_send_bulk_sent_unsubscribed_and_empty_skipped() -> None:
    gate = ApprovalGate(auto_approve_in_test=True)
    backend = _RecordingBackend(status="sent")
    store = UnsubscribeStore()
    store.add("skip@example.com")
    agent = EmailAgent(_DummyRouter(), gate, backend=backend, unsubscribe_store=store)

    results = await agent.send_bulk(
        recipients=[
            {"email": "a@example.com", "name": "A"},
            {"email": "skip@example.com", "name": "S"},
            {"email": "", "name": "E"},
        ],
        subject="Hi {{name}}",
        body_text="Body {{name}}",
        delay_between_s=0,
    )

    assert [row.status for row in results] == ["sent", "blocked:unsubscribed", "failed"]
    assert len(backend.calls) == 1
    assert backend.calls[0].subject == "Hi A"


@pytest.mark.asyncio
async def test_email_agent_audit_log_entries_for_send_blocked_and_denied() -> None:
    gate = ApprovalGate(default_timeout_seconds=1.0)
    backend = _RecordingBackend(status="sent")
    store = UnsubscribeStore()
    store.add("blocked@example.com")
    agent = EmailAgent(_DummyRouter(), gate, backend=backend, unsubscribe_store=store)

    async def approve_sink(event: dict[str, Any]) -> None:
        gate.approve(str(event["request_id"]), approver="tester")

    async def deny_sink(event: dict[str, Any]) -> None:
        gate.deny(str(event["request_id"]), reason="not_allowed")

    sent = await agent.send("ok@example.com", "Hi", "Body", event_sink=approve_sink)
    blocked = await agent.send("blocked@example.com", "Hi", "Body", event_sink=approve_sink)
    denied = await agent.send("deny@example.com", "Hi", "Body", event_sink=deny_sink)

    assert sent.status == "sent"
    assert blocked.status == "blocked:unsubscribed"
    assert denied.status == "denied:not_allowed"
    assert len(agent.send_log) == 3
    statuses = [row["status"] for row in agent.send_log]
    assert "sent" in statuses
    assert "blocked:unsubscribed" in statuses
    assert any(row.startswith("denied:") for row in statuses)
