"""Tests for mobile sync storage and webchat mobile sync APIs."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archon.interfaces.api.server import app
from archon.mobile.sync_store import MobileSyncStore


@pytest.fixture(autouse=True)
def _mobile_sync_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "mobile-sync-openrouter-key")
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")
    monkeypatch.setenv("ARCHON_MOBILE_SYNC_DB", str(_tmp_db("env-mobile-sync")))
    monkeypatch.setenv("ARCHON_DEVICE_TOKENS_DB", str(_tmp_db("env-device-tokens")))
    monkeypatch.setenv("ARCHON_ANALYTICS_DB", str(_tmp_db("env-analytics")))


def _tmp_db(prefix: str) -> Path:
    root = Path("archon/tests/_tmp_mobile_sync")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{prefix}-{uuid.uuid4().hex[:8]}.sqlite3"


def _issue_identified_session(client: TestClient, tenant_id: str) -> tuple[str, str]:
    issued = client.post("/webchat/token", json={})
    assert issued.status_code == 200
    body = issued.json()
    session_id = body["session"]["session_id"]
    upgraded = client.post(
        "/webchat/upgrade",
        json={"token": body["token"], "tenant_id": tenant_id, "tier": "growth"},
    )
    assert upgraded.status_code == 200
    return session_id, upgraded.json()["token"]


def test_mobile_sync_store_cursor_paginates_idempotently() -> None:
    store = MobileSyncStore(path=_tmp_db("store-cursor"))
    base = time.time()
    store.record_event("tenant-a", "approval_required", {"request_id": "a-1"}, created_at=base - 3)
    store.record_event("tenant-a", "approval_required", {"request_id": "a-2"}, created_at=base - 2)
    store.record_event("tenant-a", "approval_resolved", {"request_id": "a-2"}, created_at=base - 1)

    first = store.list_events("tenant-a", since=0.0, limit=2)
    second = store.list_events("tenant-a", cursor=first.next_cursor, limit=2)
    second_repeat = store.list_events("tenant-a", cursor=first.next_cursor, limit=2)

    assert [row.payload["request_id"] for row in first.events] == ["a-1", "a-2"]
    assert first.has_more is True
    assert [row.payload["request_id"] for row in second.events] == ["a-2"]
    assert second.has_more is False
    assert [row.event_id for row in second.events] == [row.event_id for row in second_repeat.events]


def test_mobile_sync_store_recovers_stale_watermark() -> None:
    store = MobileSyncStore(path=_tmp_db("store-recovery"))
    store.record_event("tenant-a", "approval_required", {"request_id": "a-1"})

    page = store.list_events("tenant-a", since=time.time() + 3600, limit=10)

    assert page.stale_watermark_recovered is True
    assert len(page.events) == 1


def test_webchat_mobile_device_registration_records_registry_and_analytics() -> None:
    with TestClient(app) as client:
        session_id, token = _issue_identified_session(client, "tenant-mobile")
        response = client.post(
            "/webchat/mobile/devices",
            json={"token": token, "platform": "ios", "device_token": "ios-device-1"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "registered"
        assert payload["session_id"] == session_id

        devices = app.state.mobile_device_registry.get_by_tenant("tenant-mobile")
        assert len(devices) == 1
        assert devices[0].token == "ios-device-1"

        events = app.state.analytics_collector.list_events(
            "tenant-mobile",
            event_type="state_change",
            limit=20,
        )
        assert any(event.properties.get("action") == "mobile_device_registered" for event in events)


def test_webchat_mobile_sync_route_is_tenant_isolated() -> None:
    with TestClient(app) as client:
        session_a, token_a = _issue_identified_session(client, "tenant-a")
        session_b, token_b = _issue_identified_session(client, "tenant-b")

        store = app.state.webchat_app.state.runtime.mobile_sync_store
        store.record_event("tenant-a", "approval_required", {"request_id": "approve-a"})
        store.record_event("tenant-b", "approval_required", {"request_id": "approve-b"})

        forbidden = client.get(
            f"/webchat/mobile/sync/{session_a}",
            params={"token": token_b, "since": 0, "page_size": 20},
        )
        tenant_a = client.get(
            f"/webchat/mobile/sync/{session_a}",
            params={"token": token_a, "since": 0, "page_size": 20},
        )
        tenant_b = client.get(
            f"/webchat/mobile/sync/{session_b}",
            params={"token": token_b, "since": 0, "page_size": 20},
        )

    assert forbidden.status_code == 403

    payload_a = tenant_a.json()
    payload_b = tenant_b.json()
    assert payload_a["tenant_id"] == "tenant-a"
    assert payload_b["tenant_id"] == "tenant-b"
    assert [row["payload"]["request_id"] for row in payload_a["notifications"]] == ["approve-a"]
    assert [row["payload"]["request_id"] for row in payload_b["notifications"]] == ["approve-b"]


def test_webchat_mobile_sync_route_flags_stale_watermark_recovery() -> None:
    with TestClient(app) as client:
        session_id, token = _issue_identified_session(client, "tenant-stale")
        store = app.state.webchat_app.state.runtime.mobile_sync_store
        store.record_event("tenant-stale", "approval_required", {"request_id": "approve-stale"})

        response = client.get(
            f"/webchat/mobile/sync/{session_id}",
            params={"token": token, "since": time.time() + 86400, "page_size": 20},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sync"]["stale_watermark_recovered"] is True
    assert payload["notifications"][0]["payload"]["request_id"] == "approve-stale"
