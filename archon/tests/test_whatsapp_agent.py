"""Tests for WhatsApp outreach backends and approval-gated agent behavior."""

from __future__ import annotations

from typing import Any

import pytest

from archon.agents.outreach.email_agent import UnsubscribeStore
from archon.agents.outreach.whatsapp_agent import (
    MetaBackend,
    TemplateMessage,
    TwilioBackend,
    WhatsAppAgent,
)
from archon.agents.outreach.whatsapp_backends import SendResult
from archon.core.approval_gate import ApprovalGate


class _DummyRouter:
    pass


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        json_data: dict[str, Any] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.content = b"{}" if json_data is not None else b""

    def json(self) -> dict[str, Any]:
        if self._json_data is None:
            raise ValueError("No JSON content")
        return self._json_data


class _FakeClient:
    response = _FakeResponse(200, json_data={})
    captured: dict[str, Any] = {}
    raised: Exception | None = None

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        del args, kwargs

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        del exc_type, exc, tb

    async def post(self, url: str, **kwargs) -> _FakeResponse:  # noqa: ANN003
        self.__class__.captured = {"url": url, **kwargs}
        if self.__class__.raised is not None:
            raise self.__class__.raised
        return self.__class__.response


class _RecordingBackend:
    def __init__(self) -> None:
        self.text_calls: list[tuple[str, str]] = []
        self.template_calls: list[tuple[str, TemplateMessage]] = []

    async def send_text(self, to: str, body: str) -> SendResult:
        self.text_calls.append((to, body))
        return SendResult(to=to, status="sent", provider="fake", provider_message_id="fake-text-1")

    async def send_template(self, to: str, template: TemplateMessage) -> SendResult:
        self.template_calls.append((to, template))
        return SendResult(to=to, status="sent", provider="fake", provider_message_id="fake-tpl-1")


@pytest.mark.asyncio
async def test_twilio_backend_success_201(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.whatsapp_backends as wa_module

    _FakeClient.response = _FakeResponse(201, json_data={"sid": "SM123"})
    _FakeClient.raised = None
    monkeypatch.setattr(wa_module.httpx, "AsyncClient", _FakeClient)

    backend = TwilioBackend(account_sid="AC123", auth_token="secret", from_number="+14155238886")
    result = await backend.send_text("+15550001111", "Hello")

    assert result.status == "sent"
    assert result.provider_message_id == "SM123"
    assert (
        _FakeClient.captured["url"]
        == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
    )
    assert _FakeClient.captured["data"]["To"] == "whatsapp:+15550001111"
    assert _FakeClient.captured["data"]["From"] == "whatsapp:+14155238886"
    assert _FakeClient.captured["auth"] == ("AC123", "secret")


@pytest.mark.asyncio
async def test_twilio_backend_auth_failure_401(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.whatsapp_backends as wa_module

    _FakeClient.response = _FakeResponse(401, text="unauthorized")
    _FakeClient.raised = None
    monkeypatch.setattr(wa_module.httpx, "AsyncClient", _FakeClient)

    backend = TwilioBackend(
        account_sid="AC123", auth_token="bad", from_number="whatsapp:+14155238886"
    )
    result = await backend.send_text("+15550001111", "Hello")

    assert result.status == "failed"
    assert result.error and "401" in result.error


@pytest.mark.asyncio
async def test_twilio_backend_exception_returns_error_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import archon.agents.outreach.whatsapp_backends as wa_module

    _FakeClient.response = _FakeResponse(201, json_data={"sid": "unused"})
    _FakeClient.raised = RuntimeError("network down")
    monkeypatch.setattr(wa_module.httpx, "AsyncClient", _FakeClient)

    backend = TwilioBackend(account_sid="AC123", auth_token="secret", from_number="+14155238886")
    result = await backend.send_text("+15550001111", "Hello")

    assert result.status == "failed"
    assert result.error and "network down" in result.error


@pytest.mark.asyncio
async def test_meta_backend_text_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.whatsapp_backends as wa_module

    _FakeClient.response = _FakeResponse(200, json_data={"messages": [{"id": "wamid.abc"}]})
    _FakeClient.raised = None
    monkeypatch.setattr(wa_module.httpx, "AsyncClient", _FakeClient)

    backend = MetaBackend(access_token="token-1", phone_number_id="phone-1")
    result = await backend.send_text("whatsapp:+15550002222", "Hi there")

    assert result.status == "sent"
    assert result.provider_message_id == "wamid.abc"
    assert _FakeClient.captured["url"] == "https://graph.facebook.com/v19.0/phone-1/messages"
    assert _FakeClient.captured["headers"]["Authorization"] == "Bearer token-1"
    assert _FakeClient.captured["json"]["type"] == "text"
    assert _FakeClient.captured["json"]["to"] == "+15550002222"
    assert _FakeClient.captured["json"]["text"]["body"] == "Hi there"


@pytest.mark.asyncio
async def test_meta_backend_template_message_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.whatsapp_backends as wa_module

    _FakeClient.response = _FakeResponse(200, json_data={"messages": [{"id": "wamid.tpl"}]})
    _FakeClient.raised = None
    monkeypatch.setattr(wa_module.httpx, "AsyncClient", _FakeClient)

    backend = MetaBackend(access_token="token-1", phone_number_id="phone-1")
    template = TemplateMessage(
        template_name="welcome_offer",
        language_code="en_US",
        components=[{"type": "body", "parameters": [{"type": "text", "text": "Ava"}]}],
    )
    result = await backend.send_template("+15550002222", template)

    assert result.status == "sent"
    payload = _FakeClient.captured["json"]
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "welcome_offer"
    assert payload["template"]["language"]["code"] == "en_US"
    assert payload["template"]["components"][0]["type"] == "body"


@pytest.mark.asyncio
async def test_meta_backend_exception_returns_error_result(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.whatsapp_backends as wa_module

    _FakeClient.response = _FakeResponse(200, json_data={"messages": [{"id": "unused"}]})
    _FakeClient.raised = RuntimeError("meta unavailable")
    monkeypatch.setattr(wa_module.httpx, "AsyncClient", _FakeClient)

    backend = MetaBackend(access_token="token-1", phone_number_id="phone-1")
    result = await backend.send_text("+15550002222", "Hi there")

    assert result.status == "failed"
    assert result.error and "meta unavailable" in result.error


@pytest.mark.asyncio
async def test_whatsapp_agent_send_text_approval_gate_fires() -> None:
    gate = ApprovalGate(default_timeout_seconds=1.0)
    backend = _RecordingBackend()
    agent = WhatsAppAgent(_DummyRouter(), gate, backend=backend)
    events: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        events.append(event)
        gate.approve(str(event["request_id"]), approver="tester")

    result = await agent.send_text("+15550001111", "Hello there", event_sink=sink)

    assert result.status == "sent"
    assert len(events) == 1
    assert events[0]["action_type"] == "send_message"
    assert events[0]["context"]["to"] == "+15550001111"
    assert backend.text_calls == [("+15550001111", "Hello there")]


@pytest.mark.asyncio
async def test_whatsapp_agent_unsubscribed_blocked_and_denial_recorded() -> None:
    gate = ApprovalGate(default_timeout_seconds=1.0)
    backend = _RecordingBackend()
    store = UnsubscribeStore()
    store.add("+15550009999")
    agent = WhatsAppAgent(_DummyRouter(), gate, backend=backend, unsubscribe_store=store)

    events: list[dict[str, Any]] = []

    async def approve_sink(event: dict[str, Any]) -> None:
        events.append(event)
        gate.approve(str(event["request_id"]), approver="tester")

    async def deny_sink(event: dict[str, Any]) -> None:
        events.append(event)
        gate.deny(str(event["request_id"]), reason="policy")

    sent = await agent.send_text("+15550001111", "Allowed", event_sink=approve_sink)
    blocked = await agent.send_text("+15550009999", "Blocked", event_sink=approve_sink)
    denied = await agent.send_text("+15550002222", "Denied", event_sink=deny_sink)

    assert sent.status == "sent"
    assert blocked.status == "blocked:unsubscribed"
    assert denied.status == "denied:policy"
    assert backend.text_calls == [("+15550001111", "Allowed")]
    assert len(agent.send_log) == 3
    statuses = [entry["status"] for entry in agent.send_log]
    assert statuses == ["sent", "blocked:unsubscribed", "denied:policy"]
    assert [event["action_type"] for event in events] == ["send_message", "send_message"]


def test_handle_inbound_parses_twilio_payload() -> None:
    gate = ApprovalGate(auto_approve_in_test=True)
    agent = WhatsAppAgent(_DummyRouter(), gate, backend=_RecordingBackend())

    payload = {
        "From": "whatsapp:+15550001111",
        "Body": "Hi from Twilio",
        "Timestamp": "1700000000",
        "MessageSid": "SM123",
    }
    message = agent.handle_inbound(payload)

    assert message is not None
    assert message.from_number == "+15550001111"
    assert message.body == "Hi from Twilio"
    assert message.timestamp == 1700000000.0
    assert message.message_id == "SM123"


def test_handle_inbound_parses_meta_payload() -> None:
    gate = ApprovalGate(auto_approve_in_test=True)
    agent = WhatsAppAgent(_DummyRouter(), gate, backend=_RecordingBackend())

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "15550002222",
                                    "id": "wamid.456",
                                    "timestamp": "1700001000",
                                    "text": {"body": "Hi from Meta"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    message = agent.handle_inbound(payload)

    assert message is not None
    assert message.from_number == "15550002222"
    assert message.body == "Hi from Meta"
    assert message.timestamp == 1700001000.0
    assert message.message_id == "wamid.456"


def test_handle_inbound_unknown_format_returns_none() -> None:
    gate = ApprovalGate(auto_approve_in_test=True)
    agent = WhatsAppAgent(_DummyRouter(), gate, backend=_RecordingBackend())

    assert agent.handle_inbound({"unexpected": "shape"}) is None
    assert agent.handle_inbound({}) is None


@pytest.mark.asyncio
async def test_send_bulk_personalization_and_unsubscribe_skip() -> None:
    gate = ApprovalGate(default_timeout_seconds=1.0)
    backend = _RecordingBackend()
    store = UnsubscribeStore()
    store.add("+15550000003")
    agent = WhatsAppAgent(_DummyRouter(), gate, backend=backend, unsubscribe_store=store)
    events: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        events.append(event)
        gate.approve(str(event["request_id"]), approver="tester")

    results = await agent.send_bulk(
        recipients=[
            {"to": "+15550000001", "first_name": "Ava"},
            {"to": "+15550000002", "first_name": "Ben"},
            {"to": "+15550000003", "first_name": "Cal"},
        ],
        body_template="Hi {{first_name}}",
        personalization_key="first_name",
        event_sink=sink,
    )

    assert [result.status for result in results] == ["sent", "sent", "blocked:unsubscribed"]
    assert backend.text_calls == [
        ("+15550000001", "Hi Ava"),
        ("+15550000002", "Hi Ben"),
    ]
    assert len(events) == 2
