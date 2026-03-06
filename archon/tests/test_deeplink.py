"""Tests for deep-link routing, approval push payloads, and webchat approval context."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from archon.interfaces.webchat.server import create_webchat_app
from archon.notifications.deeplink import DeepLinkRouter


@pytest.fixture(autouse=True)
def _jwt_secret_fixture() -> None:
    previous = os.environ.get("ARCHON_JWT_SECRET")
    os.environ["ARCHON_JWT_SECRET"] = previous or "archon-dev-secret-change-me-32-bytes"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("ARCHON_JWT_SECRET", None)
        else:
            os.environ["ARCHON_JWT_SECRET"] = previous


class _GateStub:
    def __init__(self) -> None:
        self.default_timeout_seconds = 120.0
        self._pending = [
            {
                "action_id": "action-1",
                "action": "external_api_call",
                "risk_level": "HIGH",
                "created_at": time.time(),
                "context": {"resource": "outbound_email"},
            }
        ]

    @property
    def pending_actions(self) -> tuple[dict[str, object], ...]:
        return tuple(self._pending)


class _OrchestratorStub:
    def __init__(self, gate: _GateStub) -> None:
        self.approval_gate = gate


def test_deeplink_router_build_encode_decode_roundtrip() -> None:
    router = DeepLinkRouter()
    link = router.build_approval_link("act-123", "send_email", "tenant-a")
    encoded = router.encode(link)
    decoded = router.decode(encoded)

    assert encoded.startswith("archon://approval?")
    assert decoded.path == "approval"
    assert decoded.params["action_id"] == "act-123"
    assert decoded.params["action"] == "send_email"
    assert decoded.params["tenant_id"] == "tenant-a"


def test_deeplink_router_decode_missing_param_raises() -> None:
    router = DeepLinkRouter()
    try:
        router.decode("archon://approval?action_id=abc&tenant_id=t1")
        raise AssertionError("Expected ValueError for missing required parameter")
    except ValueError as exc:
        assert "Missing approval deep-link params" in str(exc)


def test_approval_push_payload_shape_for_fcm_and_apns() -> None:
    router = DeepLinkRouter()
    payload = router.build_approval_push_payload(
        tenant_id="tenant-a",
        action_id="action-9",
        action_name="publish_content",
    )
    fcm = payload.to_fcm()
    apns = payload.to_apns()

    assert payload.data["action_id"] == "action-9"
    assert "deep_link" in payload.data
    assert fcm["data"]["action_id"] == "action-9"
    assert "data" in fcm
    assert apns["custom_data"]["action_id"] == "action-9"
    assert "custom_data" in apns


def test_webchat_approval_context_message_returns_context() -> None:
    app = create_webchat_app(orchestrator=_OrchestratorStub(_GateStub()))
    with TestClient(app) as client:
        token_payload = client.post("/token", json={}).json()
        token = token_payload["token"]
        session_id = token_payload["session"]["session_id"]
        with client.websocket_connect(f"/ws/{session_id}?token={token}") as ws:
            restored = ws.receive_json()
            assert restored["type"] == "session_restored"
            ws.send_json(
                {
                    "type": "message",
                    "content": "__approval_context__",
                    "action_id": "action-1",
                }
            )
            payload = ws.receive_json()
            assert payload["type"] == "approval_context"
            assert payload["action_id"] == "action-1"
            assert payload["action"] == "external_api_call"


def test_webchat_approval_context_unknown_action_returns_error() -> None:
    app = create_webchat_app(orchestrator=_OrchestratorStub(_GateStub()))
    with TestClient(app) as client:
        token_payload = client.post("/token", json={}).json()
        token = token_payload["token"]
        session_id = token_payload["session"]["session_id"]
        with client.websocket_connect(f"/ws/{session_id}?token={token}") as ws:
            _ = ws.receive_json()
            ws.send_json(
                {
                    "type": "message",
                    "content": "__approval_context__",
                    "action_id": "unknown-action",
                }
            )
            payload = ws.receive_json()
            assert payload["type"] == "error"
            assert payload["error"] == "approval_request_not_found"
