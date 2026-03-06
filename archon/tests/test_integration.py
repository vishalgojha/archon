"""End-to-end smoke tests across ARCHON API, WebSocket, approvals, and transports."""

from __future__ import annotations

import os
import socketserver
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

import jwt
import pytest
from fastapi.testclient import TestClient

from archon.agents.outbound.email_agent import SMTPConfig, SMTPEmailTransport
from archon.interfaces.api.rate_limit import InMemoryTierRateLimitStore, set_rate_limit_store
from archon.interfaces.api.server import app
from archon.validate_config import validate_config


def _auth_token(*, tenant: str = "tenant-integration", tier: str = "business") -> str:
    return jwt.encode(
        {"sub": tenant, "tier": tier},
        "archon-dev-secret-change-me-32-bytes",
        algorithm="HS256",
    )


def _auth_headers(*, tenant: str = "tenant-integration", tier: str = "business") -> dict[str, str]:
    return {"Authorization": f"Bearer {_auth_token(tenant=tenant, tier=tier)}"}


@pytest.fixture(autouse=True)
def _openrouter_key_fixture() -> Iterator[None]:
    previous = os.environ.get("OPENROUTER_API_KEY")
    previous_jwt = os.environ.get("ARCHON_JWT_SECRET")
    os.environ["OPENROUTER_API_KEY"] = previous or "integration-openrouter-key"
    os.environ["ARCHON_JWT_SECRET"] = previous_jwt or "archon-dev-secret-change-me-32-bytes"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("OPENROUTER_API_KEY", None)
        else:
            os.environ["OPENROUTER_API_KEY"] = previous
        if previous_jwt is None:
            os.environ.pop("ARCHON_JWT_SECRET", None)
        else:
            os.environ["ARCHON_JWT_SECRET"] = previous_jwt


class _SMTPCaptureServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int]) -> None:
        super().__init__(server_address, _SMTPHandler)
        self.messages: list[str] = []


class _SMTPHandler(socketserver.StreamRequestHandler):
    def _send(self, line: bytes) -> None:
        self.wfile.write(line)
        self.wfile.flush()

    def handle(self) -> None:
        self._send(b"220 localhost ARCHON SMTP\r\n")
        in_data = False
        data_lines: list[str] = []

        while True:
            raw = self.rfile.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            upper = line.upper()

            if in_data:
                if line == ".":
                    self.server.messages.append("\n".join(data_lines))  # type: ignore[attr-defined]
                    data_lines = []
                    in_data = False
                    self._send(b"250 Message accepted\r\n")
                else:
                    if line.startswith(".."):
                        line = line[1:]
                    data_lines.append(line)
                continue

            if upper.startswith("EHLO") or upper.startswith("HELO"):
                self._send(b"250-localhost\r\n250 OK\r\n")
            elif upper.startswith("MAIL FROM"):
                self._send(b"250 OK\r\n")
            elif upper.startswith("RCPT TO"):
                self._send(b"250 OK\r\n")
            elif upper.startswith("DATA"):
                in_data = True
                self._send(b"354 End data with <CR><LF>.<CR><LF>\r\n")
            elif upper.startswith("RSET") or upper.startswith("NOOP"):
                self._send(b"250 OK\r\n")
            elif upper.startswith("QUIT"):
                self._send(b"221 Bye\r\n")
                break
            elif upper.startswith("STARTTLS"):
                self._send(b"454 TLS not available\r\n")
            else:
                self._send(b"250 OK\r\n")


@contextmanager
def _smtp_capture_server() -> Iterator[_SMTPCaptureServer]:
    server = _SMTPCaptureServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def _collect_ws_events(
    websocket,
    *,
    stop_on_result: bool = True,
    max_messages: int = 250,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    events: list[dict[str, Any]] = []
    result: dict[str, Any] | None = None
    for _ in range(max_messages):
        message = websocket.receive_json()
        if message.get("type") == "event":
            payload = message.get("payload")
            if isinstance(payload, dict):
                events.append(payload)
        if message.get("type") == "result":
            payload = message.get("payload")
            if isinstance(payload, dict):
                result = payload
                if stop_on_result:
                    break
    return events, result


def test_full_debate_flow_streams_events_with_budget_snapshot() -> None:
    """Debate smoke: response content/confidence and cost/budget telemetry in events."""

    token = _auth_token(tenant="tenant-debate", tier="business")
    with TestClient(app) as client:
        with client.websocket_connect(f"/v1/tasks/ws?token={token}") as websocket:
            websocket.send_json(
                {
                    "goal": "Explain the CAP theorem in simple terms and give one practical tradeoff example.",
                    "mode": "debate",
                }
            )
            events, result = _collect_ws_events(websocket)

    assert result is not None
    assert isinstance(result.get("final_answer"), str)
    assert result["final_answer"].strip()
    assert isinstance(result.get("confidence"), int)

    types = {event.get("type") for event in events}
    assert "task_started" in types
    assert "task_completed" in types
    assert any(event.get("type") == "cost_update" for event in events) or any(
        "budget" in event for event in events
    )


def test_full_growth_flow_runs_prospector_and_icp() -> None:
    """Growth smoke: verify core growth swarm agents execute."""

    with TestClient(app) as client:
        response = client.post(
            "/v1/tasks",
            json={
                "goal": "Expand outbound pipeline for B2B clinic automation software",
                "mode": "growth",
                "context": {
                    "prospect_description": (
                        "Regional chain of clinics using WhatsApp heavily, weak follow-up, "
                        "manual scheduling, and high no-show rates."
                    )
                },
            },
            headers=_auth_headers(tenant="tenant-growth", tier="growth"),
        )

    assert response.status_code == 200
    payload = response.json()
    reports = payload["growth"]["agent_reports"]
    names = {row["agent"] for row in reports}
    assert "ProspectorAgent" in names
    assert "ICPAgent" in names


def test_auth_flow_401_429_and_valid_pro_equivalent_token_200() -> None:
    """Auth smoke: unauthenticated denied, free tier rate-limited, business tier allowed."""

    previous_store = app.state.rate_limit_store
    app.state.rate_limit_store = InMemoryTierRateLimitStore(
        limits={
            "free": "1/minute",
            "growth": "50/minute",
            "business": "50/minute",
            "enterprise": "50/minute",
        }
    )
    set_rate_limit_store(app.state.rate_limit_store)

    try:
        with TestClient(app) as client:
            unauth = client.post("/v1/tasks", json={"goal": "Ping", "mode": "debate"})
            free_1 = client.post(
                "/v1/tasks",
                json={"goal": "First free-tier request", "mode": "debate"},
                headers=_auth_headers(tenant="tenant-free-auth", tier="free"),
            )
            free_2 = client.post(
                "/v1/tasks",
                json={"goal": "Second free-tier request", "mode": "debate"},
                headers=_auth_headers(tenant="tenant-free-auth", tier="free"),
            )
            pro_equivalent = client.post(
                "/v1/tasks",
                json={"goal": "Pro/business request", "mode": "debate"},
                headers=_auth_headers(tenant="tenant-pro-auth", tier="business"),
            )
    finally:
        app.state.rate_limit_store = previous_store
        set_rate_limit_store(previous_store)

    assert unauth.status_code == 401
    assert free_1.status_code == 200
    assert free_2.status_code == 429
    assert pro_equivalent.status_code == 200


def test_approval_gate_integration_emits_event_and_completes_after_approve() -> None:
    """Approval smoke: emit approval_required over WS, approve via API, then complete."""

    token = _auth_token(tenant="tenant-approval", tier="business")
    headers = _auth_headers(tenant="tenant-approval", tier="business")

    with TestClient(app) as client:
        with client.websocket_connect(f"/v1/tasks/ws?token={token}") as websocket:
            websocket.send_json(
                {
                    "goal": "Create a growth action plan and execute one guarded operation.",
                    "mode": "growth",
                    "context": {
                        "guarded_action": {
                            "action_type": "outbound_sms",
                            "payload": {"to": "+15550001111", "message": "Follow-up"},
                        }
                    },
                }
            )

            approval_id = ""
            result_payload: dict[str, Any] | None = None
            approval_seen = False

            for _ in range(300):
                frame = websocket.receive_json()
                if frame.get("type") == "event":
                    event = frame.get("payload", {})
                    if event.get("type") == "approval_required":
                        approval_seen = True
                        approval_id = str(event.get("request_id", "")).strip()
                        assert approval_id
                        approve = client.post(
                            f"/v1/approvals/{approval_id}/approve",
                            json={},
                            headers=headers,
                        )
                        assert approve.status_code == 200
                if frame.get("type") == "result":
                    payload = frame.get("payload")
                    if isinstance(payload, dict):
                        result_payload = payload
                    break

    assert approval_seen is True
    assert result_payload is not None
    decision = result_payload["growth"].get("guarded_action_decision", {})
    assert decision.get("approved") is True
    assert decision.get("request_id")


def test_webchat_flow_anonymous_ws_stream_done_and_session_restore() -> None:
    """WebChat smoke: anonymous token, token stream + done, reconnect and restore history."""

    with TestClient(app) as client:
        token_response = client.post("/webchat/token", json={})
        assert token_response.status_code == 200
        token_payload = token_response.json()
        session_id = token_payload["session"]["session_id"]
        token = token_payload["token"]
        ws_path = f"/webchat/ws/{session_id}?token={token}"

        with client.websocket_connect(ws_path) as ws_first:
            restored_1 = ws_first.receive_json()
            assert restored_1["type"] == "session_restored"
            ws_first.send_json({"type": "message", "content": "Hello from integration smoke test"})

            saw_token = False
            saw_done = False
            for _ in range(400):
                frame = ws_first.receive_json()
                frame_type = frame.get("type")
                if frame_type == "assistant_token":
                    saw_token = True
                if frame_type == "done":
                    saw_done = True
                    break
            assert saw_token is True
            assert saw_done is True

        with client.websocket_connect(ws_path) as ws_second:
            restored_2 = ws_second.receive_json()
            assert restored_2["type"] == "session_restored"
            history = restored_2.get("messages", [])
            assert isinstance(history, list)
            assert len(history) >= 2


def test_email_flow_with_auto_approve_in_test_and_smtp_capture() -> None:
    """Email smoke: auto-approve gate + real local SMTP transport + footer/personalization check."""

    with _smtp_capture_server() as smtp_server:
        smtp_port = int(smtp_server.server_address[1])
        smtp_transport = SMTPEmailTransport(
            SMTPConfig(
                host="127.0.0.1",
                port=smtp_port,
                from_email="noreply@archon.local",
                use_starttls=False,
                use_tls=False,
            )
        )

        with TestClient(app) as client:
            original_transport = app.state.orchestrator.email_agent.transport
            original_auto = app.state.orchestrator.approval_gate.auto_approve_in_test
            app.state.orchestrator.email_agent.transport = smtp_transport
            app.state.orchestrator.approval_gate.auto_approve_in_test = True

            try:
                personalized_body = (
                    "Hi Aisha,\n\n"
                    "Thanks for exploring ARCHON for your outreach workflows.\n"
                    "We can tailor onboarding for your use case.\n\n"
                    "To unsubscribe, reply STOP or contact support@archon.local.\n"
                )
                response = client.post(
                    "/v1/outbound/email",
                    json={
                        "to_email": "aisha@example.com",
                        "subject": "Aisha - ARCHON onboarding follow-up",
                        "body": personalized_body,
                        "metadata": {"campaign": "integration-smoke"},
                    },
                    headers=_auth_headers(tenant="tenant-email", tier="business"),
                )
            finally:
                app.state.orchestrator.email_agent.transport = original_transport
                app.state.orchestrator.approval_gate.auto_approve_in_test = original_auto

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "sent"
        assert payload["result"]["metadata"]["provider"] == "smtp"

        deadline = time.time() + 4.0
        while time.time() < deadline and not smtp_server.messages:
            time.sleep(0.05)
        assert smtp_server.messages, "Expected at least one SMTP DATA payload."
        combined = "\n".join(smtp_server.messages)
        assert "Hi Aisha" in combined
        assert "To unsubscribe, reply STOP" in combined


def test_validate_config_dry_run_schema_and_budget_sanity() -> None:
    """Config validation smoke: dry-run exits cleanly with schema + budget checks passing."""

    report = validate_config(path="config.archon.yaml", dry_run=True)
    assert report.schema_valid is True
    assert report.ok is True
    assert not any("Budget sanity failed" in item for item in report.errors)


@pytest.mark.parametrize(
    ("provider_filter", "case_id"),
    [
        (None, 1),
        (None, 2),
        (None, 3),
        ("openrouter", 4),
        ("openrouter", 5),
        ("openrouter", 6),
        ("anthropic", 7),
        ("anthropic", 8),
        ("anthropic", 9),
        ("openai", 10),
        ("openai", 11),
        ("openai", 12),
        ("gemini", 13),
        ("gemini", 14),
        ("gemini", 15),
        ("groq", 16),
        ("groq", 17),
        ("groq", 18),
        ("mistral", 19),
        ("mistral", 20),
        ("together", 21),
        ("together", 22),
        ("fireworks", 23),
        ("fireworks", 24),
        ("ollama", 25),
        ("ollama", 26),
        ("custom-provider-a", 27),
        ("custom-provider-b", 28),
        ("custom-provider-c", 29),
        ("custom-provider-d", 30),
    ],
)
def test_validate_config_dry_run_provider_matrix(
    provider_filter: str | None,
    case_id: int,
) -> None:
    """Repeated dry-run matrix to smoke-check config validation paths across provider filters."""

    del case_id
    report = validate_config(path="config.archon.yaml", dry_run=True, provider=provider_filter)
    assert report.schema_valid is True
    assert report.ok is True
