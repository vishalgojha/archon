"""Tests for LinkedIn outreach researcher, senders, and orchestrator."""

from __future__ import annotations

from typing import Any

import pytest

from archon.agents.outreach.linkedin_agent import (
    ConnectionAgent,
    LinkedInAgent,
    MessageAgent,
    NotConnectedError,
    ProfileResearcher,
    SendResult,
)
from archon.agents.outreach.linkedin_types import LinkedInProfile, to_urn
from archon.core.approval_gate import ApprovalGate


class _DummyRouter:
    pass


class _FakeResponse:
    def __init__(self, status_code: int, *, json_data: dict[str, Any] | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self) -> dict[str, Any]:
        if self._json_data is None:
            raise ValueError("No JSON data")
        return self._json_data


class _FakeAsyncClient:
    responses: list[_FakeResponse] = []
    calls: list[dict[str, Any]] = []

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        del args, kwargs

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        del exc_type, exc, tb

    async def request(self, method: str, url: str, **kwargs) -> _FakeResponse:  # noqa: ANN003
        self.__class__.calls.append({"method": method, "url": url, **kwargs})
        if not self.__class__.responses:
            return _FakeResponse(500, text="No response queued")
        return self.__class__.responses.pop(0)


def _reset_client() -> None:
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.calls = []


@pytest.mark.asyncio
async def test_profile_researcher_fetch_profile_cache_hit_and_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import archon.agents.outreach.linkedin_clients as clients_module

    _reset_client()
    _FakeAsyncClient.responses = [
        _FakeResponse(
            200,
            json_data={
                "entityUrn": "urn:li:person:ava",
                "name": "Ava Doe",
                "headline": "Engineer",
                "company": "Acme",
                "location": "NYC",
                "summary": "Builder",
                "skills": [{"name": "Python"}],
            },
        ),
        _FakeResponse(
            200,
            json_data={
                "elements": [
                    {"entityUrn": "urn:li:person:ben", "name": "Ben Ray", "company": "Acme"},
                    {"entityUrn": "urn:li:person:cal", "name": "Cal Lin", "company": "Beta"},
                ]
            },
        ),
    ]
    monkeypatch.setattr(clients_module.httpx, "AsyncClient", _FakeAsyncClient)

    researcher = ProfileResearcher(access_token="token-1")
    first = await researcher.fetch_profile("https://www.linkedin.com/in/ava")
    second = await researcher.fetch_profile("urn:li:person:ava")
    found = await researcher.search_people("engineer", company="Acme")

    assert first.urn == "urn:li:person:ava"
    assert first.name == "Ava Doe"
    assert second == first
    assert len(_FakeAsyncClient.calls) == 2
    assert _FakeAsyncClient.calls[1]["url"].endswith("/search")
    assert len(found) == 2
    assert [item.name for item in found] == ["Ben Ray", "Cal Lin"]


@pytest.mark.asyncio
async def test_connection_agent_send_connection_request_gate_and_note_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import archon.agents.outreach.linkedin_clients as clients_module

    _reset_client()
    _FakeAsyncClient.responses = [_FakeResponse(201, json_data={"id": "invite-1"})]
    monkeypatch.setattr(clients_module.httpx, "AsyncClient", _FakeAsyncClient)

    gate = ApprovalGate(default_timeout_seconds=1.0)
    agent = ConnectionAgent(gate, access_token="token-1")
    events: list[dict[str, Any]] = []

    async def approve_sink(event: dict[str, Any]) -> None:
        events.append(event)
        gate.approve(str(event["request_id"]), approver="tester")

    long_note = "x" * 350
    result = await agent.send_connection_request(
        "urn:li:person:target",
        long_note,
        event_sink=approve_sink,
    )

    assert result.status == "sent"
    assert len(events) == 1
    assert events[0]["action_type"] == "send_message"
    assert len(_FakeAsyncClient.calls) == 1
    sent_note = _FakeAsyncClient.calls[0]["json"]["message"]
    assert len(sent_note) == 300
    assert sent_note.endswith("...")


@pytest.mark.asyncio
async def test_connection_agent_denial_blocks_send(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.agents.outreach.linkedin_clients as clients_module

    _reset_client()
    _FakeAsyncClient.responses = [_FakeResponse(201, json_data={"id": "invite-ignored"})]
    monkeypatch.setattr(clients_module.httpx, "AsyncClient", _FakeAsyncClient)

    gate = ApprovalGate(default_timeout_seconds=1.0)
    agent = ConnectionAgent(gate, access_token="token-1")

    async def deny_sink(event: dict[str, Any]) -> None:
        gate.deny(str(event["request_id"]), reason="policy")

    result = await agent.send_connection_request("urn:li:person:target", "hello", event_sink=deny_sink)

    assert result.status == "denied:policy"
    assert _FakeAsyncClient.calls == []


@pytest.mark.asyncio
async def test_message_agent_send_dm_connected_and_not_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import archon.agents.outreach.linkedin_clients as clients_module

    _reset_client()
    _FakeAsyncClient.responses = [_FakeResponse(201, json_data={"id": "msg-1"})]
    monkeypatch.setattr(clients_module.httpx, "AsyncClient", _FakeAsyncClient)

    gate = ApprovalGate(default_timeout_seconds=1.0)

    async def connected_status(_to_urn: str) -> str:
        return "connected"

    agent = MessageAgent(gate, access_token="token-1", status_checker=connected_status)
    events: list[dict[str, Any]] = []

    async def approve_sink(event: dict[str, Any]) -> None:
        events.append(event)
        gate.approve(str(event["request_id"]), approver="tester")

    sent = await agent.send_dm("urn:li:person:ava", "Hi Ava", event_sink=approve_sink)
    assert sent.status == "sent"
    assert sent.provider_message_id == "msg-1"
    assert len(events) == 1
    assert len(_FakeAsyncClient.calls) == 1

    _reset_client()

    async def pending_status(_to_urn: str) -> str:
        return "pending"

    not_connected = MessageAgent(gate, access_token="token-1", status_checker=pending_status)
    with pytest.raises(NotConnectedError):
        await not_connected.send_dm("urn:li:person:ava", "Hi Ava")
    assert _FakeAsyncClient.calls == []


@pytest.mark.asyncio
async def test_linkedin_agent_research_and_connect_personalizes_note_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import archon.agents.outreach.linkedin_clients as clients_module

    _reset_client()
    _FakeAsyncClient.responses = [
        _FakeResponse(
            200,
            json_data={"entityUrn": "urn:li:person:ava", "name": "Ava Doe", "company": "Acme"},
        ),
        _FakeResponse(201, json_data={"id": "invite-2"}),
    ]
    monkeypatch.setattr(clients_module.httpx, "AsyncClient", _FakeAsyncClient)

    gate = ApprovalGate(default_timeout_seconds=1.0)
    researcher = ProfileResearcher(access_token="token-1")
    connection = ConnectionAgent(gate, access_token="token-1")
    agent = LinkedInAgent(
        _DummyRouter(),
        gate,
        researcher=researcher,
        connection_agent=connection,
        campaign_delay_seconds=0.0,
    )

    async def approve_sink(event: dict[str, Any]) -> None:
        gate.approve(str(event["request_id"]), approver="tester")

    result = await agent.research_and_connect(
        "https://www.linkedin.com/in/ava",
        "Hi {{name}} from {{company}}",
        personalization={"company": "Acme"},
        event_sink=approve_sink,
    )

    assert result.status == "sent"
    assert _FakeAsyncClient.calls[1]["json"]["message"] == "Hi Ava Doe from Acme"
    assert len(agent.send_log) == 1
    assert agent.send_log[0]["action"] == "connection_request"


class _StubResearcher:
    async def fetch_profile(self, linkedin_url: str) -> LinkedInProfile:
        urn = to_urn(linkedin_url)
        return LinkedInProfile(urn=urn, name=linkedin_url, headline="", company="", location="", summary="", skills=[])


class _StubMessageAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def send_dm(
        self,
        to_urn_value: str,
        body: str,
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> SendResult:
        del event_sink, timeout_seconds
        self.calls.append((to_urn_value, body))
        return SendResult(to_urn_value, "sent", provider_message_id=f"msg-{len(self.calls)}")


@pytest.mark.asyncio
async def test_linkedin_agent_campaign_respects_daily_cap_and_audit_log() -> None:
    gate = ApprovalGate(auto_approve_in_test=True)
    stub_message = _StubMessageAgent()
    agent = LinkedInAgent(
        _DummyRouter(),
        gate,
        researcher=_StubResearcher(),
        connection_agent=ConnectionAgent(gate, access_token="token-1"),
        message_agent=stub_message,  # type: ignore[arg-type]
        campaign_delay_seconds=0.0,
    )

    results = await agent.campaign(
        targets=["alpha", "beta", "gamma"],
        message_template="Hello {{name}}",
        max_per_day=2,
    )

    assert [item.status for item in results] == ["sent", "sent", "skipped:daily_cap"]
    assert [item[1] for item in stub_message.calls] == ["Hello alpha", "Hello beta"]
    assert len(stub_message.calls) == 2
    assert [entry["action"] for entry in agent.send_log] == ["dm", "dm", "campaign_skip"]
