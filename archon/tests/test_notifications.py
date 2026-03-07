"""Tests for push backends, device registry, and approval push bridge."""

from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import archon.notifications.approval_notifier as approval_notifier_mod
import archon.notifications.push as push_mod
from archon.core.approval_gate import ApprovalDeniedError, ApprovalGate
from archon.mobile.sync_store import MobileSyncStore
from archon.notifications.approval_notifier import wrap_gate
from archon.notifications.device_registry import DeviceRegistry, DeviceToken
from archon.notifications.push import APNsBackend, FCMBackend, Notification, PushResult


def _tmp_db(prefix: str) -> Path:
    root = Path("archon/tests/_tmp_notifications")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{prefix}-{uuid.uuid4().hex[:8]}.sqlite3"


def _tmp_file(prefix: str, suffix: str) -> Path:
    root = Path("archon/tests/_tmp_notifications")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{prefix}-{uuid.uuid4().hex[:8]}{suffix}"


@dataclass
class _FakeResponse:
    status_code: int
    text: str = ""
    payload: dict[str, Any] | None = None

    def json(self) -> dict[str, Any]:
        return self.payload or {}


def _device_token(
    *, token_id: str = "tok-1", tenant_id: str = "tenant-1", platform: str = "android"
) -> DeviceToken:
    return DeviceToken(
        token_id=token_id,
        tenant_id=tenant_id,
        platform=platform,
        token=f"{platform}-device-token",
        created_at=time.time(),
    )


def test_fcm_backend_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeResponse(status_code=200, payload={"name": "projects/demo/messages/msg-1"})

    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr(push_mod.httpx, "post", fake_post)

    backend = FCMBackend(project_id="demo-project", server_key="legacy-key")
    result = backend.send(
        _device_token(platform="android"),
        Notification(title="Approval required", body="Check action", data={"action_id": "a-1"}),
    )

    assert result.success is True
    assert result.status_code == 200
    assert result.stale is False
    assert captured["url"].endswith("/v1/projects/demo-project/messages:send")
    assert captured["kwargs"]["headers"]["Authorization"] == "key=legacy-key"
    assert captured["kwargs"]["json"]["message"]["notification"]["title"] == "Approval required"


def test_fcm_backend_invalid_token_marks_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, **kwargs):  # type: ignore[no-untyped-def]
        del url, kwargs
        return _FakeResponse(status_code=404, text='{"error":"token-not-found"}')

    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr(push_mod.httpx, "post", fake_post)

    backend = FCMBackend(project_id="demo-project", server_key="legacy-key")
    result = backend.send(
        _device_token(token_id="stale-token", platform="android"),
        Notification(title="t", body="b"),
    )

    assert result.success is False
    assert result.status_code == 404
    assert result.stale is True


def test_fcm_backend_silent_background_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeResponse(status_code=200, payload={"name": "projects/demo/messages/msg-1"})

    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr(push_mod.httpx, "post", fake_post)

    backend = FCMBackend(project_id="demo-project", server_key="legacy-key")
    result = backend.send(
        _device_token(platform="android"),
        Notification(
            title="",
            body="",
            data={"kind": "background_sync", "silent": "true"},
            silent=True,
            sound=None,
        ),
    )

    assert result.success is True
    message = captured["kwargs"]["json"]["message"]
    assert "notification" not in message
    assert message["android"]["priority"] == "high"
    assert message["apns"]["headers"]["apns-push-type"] == "background"
    assert message["apns"]["payload"]["aps"]["content-available"] == 1


def test_fcm_backend_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, **kwargs):  # type: ignore[no-untyped-def]
        del url, kwargs
        return _FakeResponse(status_code=401, text='{"error":"unauthorized"}')

    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr(push_mod.httpx, "post", fake_post)

    backend = FCMBackend(project_id="demo-project", server_key="legacy-key")
    result = backend.send(_device_token(platform="android"), Notification(title="t", body="b"))

    assert result.success is False
    assert result.status_code == 401
    assert result.stale is False


def test_apns_backend_headers_and_jwt_format(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    key_file = _tmp_file("apns-key", ".p8")
    key_file.write_text("invalid-private-key", encoding="utf-8")

    def fake_post(url: str, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeResponse(status_code=200, text='{"reason":"Success"}')

    monkeypatch.setattr(push_mod.httpx, "post", fake_post)
    monkeypatch.setenv("APNS_KEY_ID", "KEY123")
    monkeypatch.setenv("APNS_TEAM_ID", "TEAM123")
    monkeypatch.setenv("APNS_KEY_FILE", str(key_file))
    monkeypatch.setenv("APNS_BUNDLE_ID", "com.archon.test")
    monkeypatch.setenv("APNS_ENV", "production")

    backend = APNsBackend()
    token = backend._generate_jwt()
    result = backend.send(
        _device_token(platform="ios"),
        Notification(
            title="Approval required", body="ARCHON needs action", data={"action_id": "a-1"}
        ),
    )

    assert token.count(".") == 2
    assert all(part for part in token.split("."))
    assert result.success is True
    assert captured["kwargs"]["headers"]["apns-topic"] == "com.archon.test"
    assert captured["kwargs"]["headers"]["apns-push-type"] == "alert"
    assert captured["kwargs"]["headers"]["authorization"].startswith("bearer ")
    assert "api.push.apple.com" in captured["url"]


def test_apns_backend_development_vs_production_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    def fake_post(url: str, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        urls.append(url)
        return _FakeResponse(status_code=200, text='{"reason":"Success"}')

    monkeypatch.setattr(push_mod.httpx, "post", fake_post)
    monkeypatch.setenv("APNS_KEY_ID", "KEY123")
    monkeypatch.setenv("APNS_TEAM_ID", "TEAM123")
    monkeypatch.setenv("APNS_KEY_FILE", str(_tmp_file("apns", ".p8")))

    monkeypatch.setenv("APNS_ENV", "development")
    APNsBackend(bundle_id="com.archon.test").send(
        _device_token(platform="ios"), Notification(title="t", body="b")
    )

    monkeypatch.setenv("APNS_ENV", "production")
    APNsBackend(bundle_id="com.archon.test").send(
        _device_token(platform="ios"), Notification(title="t", body="b")
    )

    assert "api.development.push.apple.com" in urls[0]
    assert "api.push.apple.com" in urls[1]


def test_apns_backend_silent_background_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeResponse(status_code=200, text='{"reason":"Success"}')

    monkeypatch.setattr(push_mod.httpx, "post", fake_post)
    monkeypatch.setenv("APNS_KEY_ID", "KEY123")
    monkeypatch.setenv("APNS_TEAM_ID", "TEAM123")
    monkeypatch.setenv("APNS_KEY_FILE", str(_tmp_file("apns-silent", ".p8")))

    backend = APNsBackend(bundle_id="com.archon.test")
    result = backend.send(
        _device_token(platform="ios"),
        Notification(
            title="",
            body="",
            data={"kind": "background_sync", "silent": "true"},
            silent=True,
            sound=None,
        ),
    )

    assert result.success is True
    assert captured["kwargs"]["headers"]["apns-push-type"] == "background"
    assert captured["kwargs"]["headers"]["apns-priority"] == "5"
    assert captured["kwargs"]["json"]["aps"]["content-available"] == 1
    assert "alert" not in captured["kwargs"]["json"]["aps"]


def test_device_registry_register_upsert_subset_and_prune() -> None:
    path = _tmp_db("registry")
    registry = DeviceRegistry(path=path)

    first = registry.register("tenant-a", "ios", "token-a")
    second = registry.register("tenant-a", "ios", "token-a")
    registry.register("tenant-b", "android", "token-b")

    assert first.token_id == second.token_id
    assert len(registry.get_by_tenant("tenant-a")) == 1
    assert len(registry.get_by_tenant("tenant-b")) == 1

    old_timestamp = time.time() - (120 * 24 * 60 * 60)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE device_tokens SET last_seen = ? WHERE token = ?", (old_timestamp, "token-a")
        )

    removed = registry.prune_stale(days=90)
    assert removed == 1
    assert registry.get_by_tenant("tenant-a") == []


class _RecordingNotifier:
    def __init__(self, registry: DeviceRegistry) -> None:
        self.registry = registry
        self.sent: list[dict[str, Any]] = []

    def send_to_tenant(self, tenant_id: str, notification: Notification) -> list[PushResult]:
        tokens = self.registry.get_tokens_for_tenant(tenant_id)
        self.sent.append(
            {
                "tenant_id": tenant_id,
                "count": len(tokens),
                "notification": notification,
            }
        )
        return [
            PushResult(
                token_id=token.token_id,
                platform=token.platform,
                success=True,
                status_code=200,
                response_body="ok",
                provider="test",
            )
            for token in tokens
        ]


@pytest.mark.asyncio
async def test_approval_notifier_wrap_gate_sends_push_and_timeout_reminder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _tmp_db("approval-notifier")
    registry = DeviceRegistry(path=path)
    sync_store = MobileSyncStore(path=_tmp_db("approval-sync-store"))
    registry.register("tenant-x", "ios", "ios-token-1")
    registry.register("tenant-x", "android", "android-token-1")

    notifier = _RecordingNotifier(registry)
    gate = ApprovalGate(default_timeout_seconds=0.02)
    wrapped = wrap_gate(
        gate,
        registry,
        notifier,  # type: ignore[arg-type]
        sync_store=sync_store,
    )

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        return None

    monkeypatch.setattr(approval_notifier_mod.asyncio, "sleep", fake_sleep)

    async def sink(event: dict[str, Any]) -> None:
        assert event["type"] == "approval_required"

    with pytest.raises(ApprovalDeniedError):
        await wrapped.check(
            action="send_message",
            context={
                "tenant_id": "tenant-x",
                "event_sink": sink,
                "timeout_seconds": 0.02,
            },
            action_id="approval-action-1",
        )

    await asyncio.sleep(0)

    assert notifier.sent
    assert notifier.sent[0]["count"] == 2
    assert "send_message" in notifier.sent[0]["notification"].body
    assert len(notifier.sent) >= 2
    assert all(call["count"] == 2 for call in notifier.sent)
    assert sleep_calls
    assert sleep_calls[0] == pytest.approx(0.01, rel=1e-6, abs=1e-6)
    sync_page = sync_store.list_events("tenant-x", since=0.0, limit=10)
    assert len(sync_page.events) == 1
    assert sync_page.events[0].event_type == "approval_required"
    assert sync_page.events[0].payload["action_id"] == "approval-action-1"
