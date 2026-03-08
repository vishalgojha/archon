"""API contract tests for task orchestration modes."""

from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from archon.agents.outbound.email_agent import EmailSendResult, OutboundEmail
from archon.agents.outbound.webchat_agent import WebChatMessage, WebChatSendResult
from archon.interfaces.api.rate_limit import InMemoryTierRateLimitStore, set_rate_limit_store
from archon.interfaces.api.server import app
from archon.versioning import resolve_git_sha
from archon.web.intent_classifier import PageIntent, SiteIntent
from archon.web.site_crawler import CrawlResult, PageData


def _auth_headers(*, tenant: str = "tenant-test", tier: str = "business") -> dict[str, str]:
    token = jwt.encode(
        {"sub": tenant, "tier": tier},
        "archon-dev-secret-change-me-32-bytes",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _set_webchat_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")


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
    assert payload["git_sha"] == resolve_git_sha()
    assert isinstance(payload["uptime_s"], (int, float))
    assert payload["uptime_s"] >= 0


def test_webchat_token_route_is_public_without_auth_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_webchat_secret(monkeypatch)
    with TestClient(app) as client:
        response = client.post("/webchat/token", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["token"]
    assert payload["session"]["session_id"].startswith("session-")


def test_webchat_session_route_is_public_with_webchat_token_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_webchat_secret(monkeypatch)
    with TestClient(app) as client:
        token_response = client.post("/webchat/token", json={})
        token_payload = token_response.json()
        session_id = token_payload["session"]["session_id"]
        token = token_payload["token"]
        response = client.get(f"/webchat/session/{session_id}", params={"token": token})

    assert token_response.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["session_id"] == session_id
    assert isinstance(payload["messages"], list)


def test_protected_route_still_requires_bearer_token() -> None:
    with TestClient(app) as client:
        response = client.get("/studio/workflows")

    assert response.status_code == 401


def test_webchat_websocket_reaches_subapp_and_returns_webchat_close_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_webchat_secret(monkeypatch)
    with TestClient(app) as client:
        token_response = client.post("/webchat/token", json={})
        token_payload = token_response.json()
        token = token_payload["token"]
        wrong_session_id = "session-mismatch"

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/webchat/ws/{wrong_session_id}?token={token}"):
                pass

    assert token_response.status_code == 200
    assert exc_info.value.code == 4003


def test_dashboard_and_studio_shells_are_public_but_studio_api_stays_protected() -> None:
    with TestClient(app) as client:
        dashboard = client.get("/dashboard")
        dashboard_asset = client.get("/dashboard/src/useARCHON.js")
        studio = client.get("/studio")
        studio_api = client.get("/studio/workflows")

    assert dashboard.status_code == 200
    assert "ARCHON Mission Control" in dashboard.text
    assert dashboard_asset.status_code == 200
    assert "window.useARCHON" in dashboard_asset.text
    assert studio.status_code == 200
    assert "ARCHON Studio" in studio.text
    assert studio_api.status_code == 401


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


def test_console_agents_tree_returns_directory_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    with TestClient(app) as client:
        response = client.get("/console/agents", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["root"] == "archon/agents"
    assert isinstance(payload["tree"], list)
    assert any(node["type"] in {"directory", "file"} for node in payload["tree"])


def test_console_agent_file_read_valid_and_invalid_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    with TestClient(app) as client:
        ok_response = client.get("/console/agents/researcher.py", headers=_auth_headers())
        missing_response = client.get("/console/agents/not-a-real-file.py", headers=_auth_headers())

    assert ok_response.status_code == 200
    ok_payload = ok_response.json()
    assert ok_payload["path"] == "researcher.py"
    assert "class ResearcherAgent" in ok_payload["content"]
    assert missing_response.status_code == 404


def test_console_agent_save_rejects_python_syntax_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    with TestClient(app) as client:
        response = client.put(
            "/console/agents/researcher.py",
            json={"content": "def broken(:\n    pass\n"},
            headers=_auth_headers(),
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["error"] == "syntax_error"


def test_console_provider_test_endpoint_returns_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    with TestClient(app) as client:
        response = client.post("/console/providers/test/openrouter", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openrouter"
    assert payload["ok"] is True
    assert payload["status"] == "healthy"


def test_console_crawl_returns_site_intent_and_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    class _FakeCrawler:
        async def crawl(self, url: str, max_pages: int, max_depth: int) -> CrawlResult:
            del max_pages, max_depth
            return CrawlResult(
                pages=[
                    PageData(
                        url=url,
                        title="Example SaaS",
                        text_content="Start free trial and pricing plans available.",
                        meta_description="Example meta",
                        h1s=["Welcome"],
                        links=[],
                        load_ms=10.0,
                    )
                ]
            )

        async def aclose(self) -> None:
            return None

    class _FakeClassifier:
        async def classify_site(self, crawl_result: CrawlResult) -> SiteIntent:
            del crawl_result
            return SiteIntent(
                primary="saas",
                secondary=["docs"],
                page_intents=[
                    PageIntent(category="saas", confidence=0.91, signals={"reason": "test"})
                ],
            )

    monkeypatch.setattr(
        "archon.interfaces.api.server.SiteCrawler", lambda *args, **kwargs: _FakeCrawler()
    )
    monkeypatch.setattr(
        "archon.interfaces.api.server.IntentClassifier", lambda *args, **kwargs: _FakeClassifier()
    )

    with TestClient(app) as client:
        response = client.post(
            "/console/crawl",
            json={"url": "https://example.com"},
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["site_intent"]["primary"] == "saas"
    assert "script_tag" in payload["embed"]
    assert "<script" in payload["embed"]["script_tag"]


def test_analytics_leaderboard_route_is_mounted_on_main_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    tenant = "tenant-analytics-mounted"

    with TestClient(app) as client:
        app.state.analytics_collector.record(
            tenant_id=tenant,
            event_type="agent_recruited",
            properties={
                "agent": "ResearcherAgent",
                "mode": "debate",
                "confidence": 81,
                "cost_usd": 0.04,
            },
        )
        response = client.get(
            "/analytics/leaderboard",
            params={"tenant_id": tenant, "scope": "tenant"},
            headers=_auth_headers(tenant=tenant, tier="business"),
        )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload
    assert payload[0]["agent"] == "ResearcherAgent"
