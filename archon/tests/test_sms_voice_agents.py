"""Tests for SMSAgent and VoiceAgent outreach flows."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from archon.agents.outreach.email_agent import UnsubscribeStore
from archon.agents.outreach.sms_agent import SMSAgent
from archon.agents.outreach.voice_agent import VoiceAgent
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
        content: bytes | None = None,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.content = content or b""

    def json(self) -> dict[str, Any]:
        if self._json_data is None:
            raise ValueError("No JSON payload")
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")


class _FakeAsyncClient:
    post_queue: list[_FakeResponse] = []
    get_queue: list[_FakeResponse] = []
    calls: list[dict[str, Any]] = []

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        del args, kwargs

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        del exc_type, exc, tb

    async def post(self, url: str, **kwargs) -> _FakeResponse:  # noqa: ANN003
        self.__class__.calls.append({"method": "POST", "url": url, **kwargs})
        if not self.__class__.post_queue:
            return _FakeResponse(500, text="No queued POST")
        return self.__class__.post_queue.pop(0)

    async def get(self, url: str, **kwargs) -> _FakeResponse:  # noqa: ANN003
        self.__class__.calls.append({"method": "GET", "url": url, **kwargs})
        if not self.__class__.get_queue:
            return _FakeResponse(500, text="No queued GET")
        return self.__class__.get_queue.pop(0)


def _reset_fake_client() -> None:
    _FakeAsyncClient.post_queue = []
    _FakeAsyncClient.get_queue = []
    _FakeAsyncClient.calls = []


@pytest.mark.asyncio
async def test_sms_send_gate_unsubscribed_and_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.sms_agent as sms_module

    _reset_fake_client()
    _FakeAsyncClient.post_queue = [_FakeResponse(201, json_data={"sid": "SM-1"})]
    monkeypatch.setattr(sms_module.httpx, "AsyncClient", _FakeAsyncClient)

    gate = ApprovalGate(default_timeout_seconds=1.0)
    store = UnsubscribeStore()
    store.add("+15550009999")
    agent = SMSAgent(
        _DummyRouter(),
        gate,
        account_sid="AC-1",
        auth_token="token-1",
        from_number="+15551110000",
        unsubscribe_store=store,
    )
    events: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        events.append(event)
        gate.approve(str(event["request_id"]), approver="tester")

    sent = await agent.send("+15550001111", "hello", event_sink=sink)
    blocked = await agent.send("+15550009999", "blocked", event_sink=sink)

    assert sent.status == "sent"
    assert blocked.status == "blocked:unsubscribed"
    assert len(events) == 1
    assert events[0]["action_type"] == "send_message"
    assert len(_FakeAsyncClient.calls) == 1
    assert len(agent.send_log) == 2
    assert [row["status"] for row in agent.send_log] == ["sent", "blocked:unsubscribed"]


@pytest.mark.asyncio
async def test_sms_body_warning_and_inbound_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.sms_agent as sms_module

    _reset_fake_client()
    _FakeAsyncClient.post_queue = [_FakeResponse(201, json_data={"sid": "SM-2"})]
    monkeypatch.setattr(sms_module.httpx, "AsyncClient", _FakeAsyncClient)

    gate = ApprovalGate(auto_approve_in_test=True)
    store = UnsubscribeStore()
    agent = SMSAgent(
        _DummyRouter(),
        gate,
        account_sid="AC-1",
        auth_token="token-1",
        from_number="+15551110000",
        unsubscribe_store=store,
    )

    result = await agent.send("+15550002222", "x" * 170)
    assert result.status == "sent"
    assert "warning" in result.metadata

    inbound = agent.handle_inbound(
        {"From": "+15550003333", "Body": "STOP", "Timestamp": "1700000000"}
    )
    assert inbound is not None
    assert inbound.from_number == "+15550003333"
    assert store.is_unsubscribed("+15550003333") is True


@pytest.mark.asyncio
async def test_sms_send_bulk_personalizes_and_skips_unsubscribed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import archon.agents.outreach.sms_agent as sms_module

    _reset_fake_client()
    _FakeAsyncClient.post_queue = [
        _FakeResponse(201, json_data={"sid": "SM-A"}),
        _FakeResponse(201, json_data={"sid": "SM-B"}),
    ]
    monkeypatch.setattr(sms_module.httpx, "AsyncClient", _FakeAsyncClient)

    gate = ApprovalGate(auto_approve_in_test=True)
    store = UnsubscribeStore()
    store.add("+15550000003")
    agent = SMSAgent(
        _DummyRouter(),
        gate,
        account_sid="AC-1",
        auth_token="token-1",
        from_number="+15551110000",
        unsubscribe_store=store,
    )

    results = await agent.send_bulk(
        [
            {"to": "+15550000001", "name": "Ava"},
            {"to": "+15550000002", "name": "Ben"},
            {"to": "+15550000003", "name": "Cal"},
        ],
        "Hi {{name}}",
    )

    assert [row.status for row in results] == ["sent", "sent", "blocked:unsubscribed"]
    bodies = [_FakeAsyncClient.calls[0]["data"]["Body"], _FakeAsyncClient.calls[1]["data"]["Body"]]
    assert bodies == ["Hi Ava", "Hi Ben"]
    assert len(_FakeAsyncClient.calls) == 2


@pytest.mark.asyncio
async def test_voice_initiate_call_gate_and_twiml_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.voice_agent as voice_module

    _reset_fake_client()
    _FakeAsyncClient.post_queue = [
        _FakeResponse(201, json_data={"sid": "CA-1", "status": "queued"})
    ]
    monkeypatch.setattr(voice_module.httpx, "AsyncClient", _FakeAsyncClient)

    gate = ApprovalGate(default_timeout_seconds=1.0)
    agent = VoiceAgent(
        _DummyRouter(),
        gate,
        account_sid="AC-1",
        auth_token="token-1",
        from_number="+15552220000",
        openai_api_key="sk-test",
    )
    events: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        events.append(event)
        gate.approve(str(event["request_id"]), approver="tester")

    twiml = "<Response><Say>Hello</Say></Response>"
    result = await agent.initiate_call("+15550001111", twiml, event_sink=sink)

    assert result.status == "queued"
    assert result.call_sid == "CA-1"
    assert len(events) == 1
    assert events[0]["action_type"] == "send_message"
    assert _FakeAsyncClient.calls[0]["url"].endswith("/Calls.json")
    assert _FakeAsyncClient.calls[0]["data"]["Twiml"] == twiml


@pytest.mark.asyncio
async def test_voice_plain_script_converts_to_twiml(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.voice_agent as voice_module

    _reset_fake_client()
    _FakeAsyncClient.post_queue = [
        _FakeResponse(201, json_data={"sid": "CA-2", "status": "queued"})
    ]
    monkeypatch.setattr(voice_module.httpx, "AsyncClient", _FakeAsyncClient)

    gate = ApprovalGate(auto_approve_in_test=True)
    agent = VoiceAgent(
        _DummyRouter(),
        gate,
        account_sid="AC-1",
        auth_token="token-1",
        from_number="+15552220000",
        openai_api_key="sk-test",
    )

    result = await agent.initiate_call("+15550001111", "Hello & team")

    assert result.status == "queued"
    twiml = _FakeAsyncClient.calls[0]["data"]["Twiml"]
    assert twiml.startswith("<Response><Say>")
    assert "Hello &amp; team" in twiml
    assert twiml.endswith("</Say></Response>")


@pytest.mark.asyncio
async def test_voice_handle_recording_webhook_transcribes(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.voice_agent as voice_module

    _reset_fake_client()
    _FakeAsyncClient.get_queue = [_FakeResponse(200, content=b"audio-bytes")]
    _FakeAsyncClient.post_queue = [
        _FakeResponse(
            200,
            json_data={"text": "Namaste", "language": "hi", "duration": 3.2, "confidence": 0.91},
        )
    ]
    monkeypatch.setattr(voice_module.httpx, "AsyncClient", _FakeAsyncClient)

    gate = ApprovalGate(auto_approve_in_test=True)
    agent = VoiceAgent(
        _DummyRouter(),
        gate,
        account_sid="AC-1",
        auth_token="token-1",
        from_number="+15552220000",
        openai_api_key="sk-test",
    )

    result = await agent.handle_recording_webhook(
        {
            "CallSid": "CA-REC-1",
            "RecordingUrl": "https://api.twilio.com/recordings/RE123",
            "RecordingDuration": "3",
        }
    )

    assert result.call_sid == "CA-REC-1"
    assert result.transcript == "Namaste"
    assert result.language == "hi"
    assert result.duration_s == 3.2
    assert result.confidence == 0.91
    assert _FakeAsyncClient.calls[0]["method"] == "GET"
    assert _FakeAsyncClient.calls[0]["url"].endswith(".mp3")
    assert _FakeAsyncClient.calls[1]["method"] == "POST"
    assert _FakeAsyncClient.calls[1]["url"] == "https://api.openai.com/v1/audio/transcriptions"


def test_vernacular_adapter_llm_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.voice_adapter as adapter_module

    fake_langdetect = types.SimpleNamespace(
        detect=lambda _text: (_ for _ in ()).throw(RuntimeError("fail"))
    )
    monkeypatch.setitem(sys.modules, "langdetect", fake_langdetect)
    adapter = adapter_module.VernacularAdapter(
        detect_fn=lambda _text: "es",
        translate_fn=lambda script, target: f"{script} ({target})",
    )

    code = adapter.detect_language("hola mundo")
    translated = adapter.translate_script("hello", "fr")

    assert code == "es"
    assert translated != ""
    assert translated.endswith("(fr)")
