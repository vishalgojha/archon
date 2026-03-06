"""API contract tests for task orchestration modes."""

from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from archon.agents.outbound.email_agent import EmailSendResult, OutboundEmail
from archon.agents.outbound.webchat_agent import WebChatMessage, WebChatSendResult
from archon.interfaces.api.rate_limit import InMemoryTierRateLimitStore, set_rate_limit_store
from archon.interfaces.api.server import app


def _auth_headers(*, tenant: str = "tenant-test", tier: str = "business") -> dict[str, str]:
    token = jwt.encode(
        {"sub": tenant, "tier": tier},
        "archon-dev-secret-change-me-32-bytes",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_post_tasks_rejects_missing_bearer_token() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/v1/tasks",
            json={"goal": "Any goal", "mode": "debate"},
        )
    assert response.status_code == 401


def test_post_tasks_debate_mode_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    with TestClient(app) as client:
        response = client.post(
            "/v1/tasks",
            json={
                "goal": "Draft a migration rollout plan",
                "mode": "debate",
            },
            headers=_auth_headers(tier="business"),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "debate"
    assert payload["debate"] is not None
    assert payload["growth"] is None
    assert isinstance(payload["debate"]["rounds"], list)
    assert len(payload["debate"]["rounds"]) == 6
    assert isinstance(payload["budget"], dict)
    assert isinstance(payload["confidence"], int)


def test_post_tasks_growth_mode_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    with TestClient(app) as client:
        response = client.post(
            "/v1/tasks",
            json={
                "goal": "Increase qualified leads in Indian pharmacy SMBs",
                "mode": "growth",
                "context": {
                    "market": "India",
                    "sector": "pharmacy",
                },
            },
            headers=_auth_headers(tier="growth"),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "growth"
    assert payload["growth"] is not None
    assert payload["debate"] is None
    assert "agent_reports" in payload["growth"]
    assert "recommended_actions" in payload["growth"]
    assert len(payload["growth"]["agent_reports"]) == 7
    assert len(payload["growth"]["recommended_actions"]) >= 7
    assert isinstance(payload["confidence"], int)


def test_post_tasks_applies_tier_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    previous_store = app.state.rate_limit_store
    app.state.rate_limit_store = InMemoryTierRateLimitStore(
        limits={
            "free": "2/minute",
            "growth": "100/minute",
            "business": "100/minute",
            "enterprise": "100/minute",
        }
    )
    set_rate_limit_store(app.state.rate_limit_store)
    try:
        with TestClient(app) as client:
            headers = _auth_headers(tenant="tenant-free-limit", tier="free")
            body = {"goal": "Draft summary", "mode": "debate"}
            first = client.post("/v1/tasks", json=body, headers=headers)
            second = client.post("/v1/tasks", json=body, headers=headers)
            third = client.post("/v1/tasks", json=body, headers=headers)
    finally:
        app.state.rate_limit_store = previous_store
        set_rate_limit_store(previous_store)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


def test_outbound_email_requires_approval_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    with TestClient(app) as client:
        response = client.post(
            "/v1/outbound/email",
            json={
                "to_email": "lead@example.com",
                "subject": "Demo follow-up",
                "body": "Can we schedule a call?",
            },
            headers=_auth_headers(tier="business"),
        )

    assert response.status_code == 409


class _FakeEmailTransport:
    async def send(self, message: OutboundEmail) -> EmailSendResult:
        del message
        return EmailSendResult(provider="fake", message_id="fake-msg-1", accepted=True, detail="ok")


def test_outbound_email_auto_approve_sends_with_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    with TestClient(app) as client:
        original_transport = app.state.orchestrator.email_agent.transport
        app.state.orchestrator.email_agent.transport = _FakeEmailTransport()
        try:
            response = client.post(
                "/v1/outbound/email",
                json={
                    "to_email": "lead@example.com",
                    "subject": "Demo follow-up",
                    "body": "Can we schedule a call?",
                    "auto_approve": True,
                },
                headers=_auth_headers(tier="business"),
            )
        finally:
            app.state.orchestrator.email_agent.transport = original_transport

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "sent"
    assert payload["result"]["metadata"]["provider"] == "fake"


def test_outbound_webchat_requires_approval_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    with TestClient(app) as client:
        response = client.post(
            "/v1/outbound/webchat",
            json={"session_id": "session-abc", "text": "Hello from ARCHON"},
            headers=_auth_headers(tier="business"),
        )

    assert response.status_code == 409


class _FakeWebChatTransport:
    async def send(self, message: WebChatMessage) -> WebChatSendResult:
        del message
        return WebChatSendResult(
            provider="fake-webchat",
            message_id="fake-webchat-1",
            accepted=True,
            detail="ok",
        )


def test_outbound_webchat_auto_approve_sends_with_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    with TestClient(app) as client:
        original_transport = app.state.orchestrator.webchat_agent.transport
        app.state.orchestrator.webchat_agent.transport = _FakeWebChatTransport()
        try:
            response = client.post(
                "/v1/outbound/webchat",
                json={
                    "session_id": "session-abc",
                    "text": "Hello from ARCHON",
                    "auto_approve": True,
                },
                headers=_auth_headers(tier="business"),
            )
        finally:
            app.state.orchestrator.webchat_agent.transport = original_transport

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "sent"
    assert payload["result"]["metadata"]["provider"] == "fake-webchat"


def test_health_endpoint_returns_status_version_and_uptime() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == app.version
    assert isinstance(payload["uptime_s"], (int, float))
    assert payload["uptime_s"] >= 0


def test_memory_timeline_endpoint_filters_by_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    rows = [
        {
            "id": 1,
            "task": "session task",
            "context": {"session_id": "session-abc"},
            "actions_taken": ["ResearcherAgent"],
            "causal_reasoning": "Reason A",
            "actual_outcome": "Outcome A",
            "delta": "Delta A",
            "reuse_conditions": "Reuse A",
            "created_at": "2026-03-06 10:00:00",
        },
        {
            "id": 2,
            "task": "other task",
            "context": {"session_id": "session-other"},
            "actions_taken": ["CriticAgent"],
            "causal_reasoning": "Reason B",
            "actual_outcome": "Outcome B",
            "delta": "Delta B",
            "reuse_conditions": "Reuse B",
            "created_at": "2026-03-06 10:01:00",
        },
    ]

    with TestClient(app) as client:
        async def fake_list_recent(*, limit: int) -> list[dict[str, object]]:
            assert limit >= 2
            return rows

        monkeypatch.setattr(app.state.orchestrator.memory_store, "list_recent", fake_list_recent)
        response = client.get("/memory/timeline", params={"session_id": "session-abc", "limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert "entries" in payload
    assert len(payload["entries"]) == 1
    entry = payload["entries"][0]
    assert entry["memory_id"] == "1"
    assert entry["content"] == "Outcome A"
    assert entry["role"] == "assistant"
