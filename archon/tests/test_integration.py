"""End-to-end smoke tests across ARCHON API, WebSocket, approvals, and transports."""

from __future__ import annotations

import asyncio
import base64
import io
import os
import socketserver
import sqlite3
import threading
import time
import uuid
import wave
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import archon.vernacular.detector as vernacular_detector_mod
from archon.agents.community.community_agent import (
    CommunityAgent,
    CommunityPost,
    ResponseComposer,
    SignalDetector,
)
from archon.agents.content.content_agent import ContentAgent, PublishTarget
from archon.agents.outbound.email_agent import SMTPConfig, SMTPEmailTransport
from archon.billing import InvoiceGenerator, UsageMeter
from archon.billing.stripe_client import UsageRecord as StripeUsageRecord
from archon.config import ArchonConfig
from archon.interfaces.api.rate_limit import InMemoryTierRateLimitStore, set_rate_limit_store
from archon.interfaces.api.server import app
from archon.marketplace.connect import CONNECT_ACCOUNT_METADATA_KEY, ConnectAccount
from archon.multimodal import MultimodalOrchestrator, TranscriptResult
from archon.onprem import DeploymentConfig, DeployValidator, DockerComposeGenerator
from archon.partners.viral_loop import ViralLoop, visitor_fingerprint
from archon.studio.workflow_serializer import deserialize, serialize
from archon.validate_config import validate_config
from archon.vernacular.detector import LanguageDetector
from archon.vernacular.pipeline import VernacularPipeline
from archon.vernacular.reasoner import VernacularReasoner

_JWT_SECRET = "archon-dev-secret-change-me-32-bytes"


def _auth_token(*, tenant: str = "tenant-integration", tier: str = "business") -> str:
    return jwt.encode(
        {"sub": tenant, "tier": tier},
        os.environ.get("ARCHON_JWT_SECRET", _JWT_SECRET),
        algorithm="HS256",
    )


def _auth_headers(*, tenant: str = "tenant-integration", tier: str = "business") -> dict[str, str]:
    return {"Authorization": f"Bearer {_auth_token(tenant=tenant, tier=tier)}"}


@pytest.fixture(autouse=True)
def _openrouter_key_fixture() -> Iterator[None]:
    previous = os.environ.get("OPENROUTER_API_KEY")
    previous_jwt = os.environ.get("ARCHON_JWT_SECRET")
    os.environ["OPENROUTER_API_KEY"] = previous or "integration-openrouter-key"
    os.environ["ARCHON_JWT_SECRET"] = _JWT_SECRET
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


def _receive_ws_json_or_fail(websocket) -> dict[str, Any]:
    try:
        frame = websocket.receive_json()
    except WebSocketDisconnect as exc:
        pytest.fail(f"WS disconnected with code {exc.code}: {exc.reason}")
    if not isinstance(frame, dict):
        pytest.fail(f"Unexpected websocket frame: {frame!r}")
    return frame


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
        message = _receive_ws_json_or_fail(websocket)
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


def _wav_bytes(duration_s: int, sample_rate: int = 8000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * duration_s * sample_rate)
    return output.getvalue()


def _set_marketplace_envs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_PARTNERS_DB", str(tmp_path / "partners.sqlite3"))
    monkeypatch.setenv(
        "ARCHON_MARKETPLACE_CONNECT_DB",
        str(tmp_path / "marketplace-connect.sqlite3"),
    )
    monkeypatch.setenv(
        "ARCHON_MARKETPLACE_REVENUE_DB",
        str(tmp_path / "marketplace-revenue.sqlite3"),
    )
    monkeypatch.setenv(
        "ARCHON_MARKETPLACE_CYCLE_DB",
        str(tmp_path / "marketplace-cycles.sqlite3"),
    )


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
                frame = _receive_ws_json_or_fail(websocket)
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


def test_vernacular_pipeline_smoke_english_detect_and_spanish_native_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vernacular smoke: detect English correctly and route Spanish to native reasoning."""

    class _LangProb:
        def __init__(self, lang: str, prob: float) -> None:
            self.lang = lang
            self.prob = prob

    def _fake_detect_langs(text: str) -> list[_LangProb]:
        lowered = text.lower()
        if "necesito" in lowered or "flujo de trabajo" in lowered:
            return [_LangProb("es", 0.97)]
        return [_LangProb("en", 0.98)]

    class _Router:
        async def invoke(self, *, role: str, prompt: str, system_prompt: str | None = None):  # type: ignore[no-untyped-def]
            del role, prompt

            class _Response:
                def __init__(self, text: str) -> None:
                    self.text = text

            if "(es)" in str(system_prompt or ""):
                return _Response("Respuesta nativa en español para el flujo solicitado.")
            return _Response("Native English response for the requested workflow.")

    monkeypatch.setattr(vernacular_detector_mod, "_langdetect_detect_langs", _fake_detect_langs)

    detector = LanguageDetector(router=None)
    reasoner = VernacularReasoner(router=_Router(), native_supported_languages={"en", "es"})
    pipeline = VernacularPipeline(detector=detector, reasoner=reasoner)

    english = pipeline.process("Please summarize this architecture decision in plain language.")
    spanish = pipeline.process("Necesito una respuesta clara sobre este flujo de trabajo.")

    assert english.detected_language == "en"
    assert spanish.detected_language == "es"
    assert spanish.method == "native_reasoning"
    assert spanish.response_language == "es"
    assert "español" in spanish.response_content.lower()


def test_partner_viral_loop_smoke_window_attribution() -> None:
    """Partner smoke: in-window conversion attributed; stale conversion excluded."""

    base = Path("archon/tests/_tmp_integration")
    base.mkdir(parents=True, exist_ok=True)
    db_path = base / f"viral-loop-smoke-{uuid.uuid4().hex[:8]}.sqlite3"
    loop = ViralLoop(path=db_path, attribution_window_hours=72)

    in_window = loop.record_impression(
        partner_id="partner-smoke",
        site_url="https://partner.example/embed",
        visitor_fingerprint=visitor_fingerprint("203.0.113.10", "Mozilla/5.0", "2026-03-06"),
    )
    loop.record_conversion(in_window.impression_id, customer_id="cust-in-window")

    outside_window = loop.record_impression(
        partner_id="partner-smoke",
        site_url="https://partner.example/embed",
        visitor_fingerprint=visitor_fingerprint("203.0.113.11", "Mozilla/5.0", "2026-03-06"),
    )
    stale_timestamp = time.time() - (73 * 3600)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE impressions SET timestamp = ? WHERE impression_id = ?",
            (stale_timestamp, outside_window.impression_id),
        )
    loop.record_conversion(outside_window.impression_id, customer_id="cust-out-window")

    funnel = loop.get_funnel("partner-smoke")
    assert funnel.impressions == 2
    assert funnel.conversions == 1
    assert funnel.conversion_rate == 0.5


def test_content_pipeline_smoke_brief_article_structure_and_queue() -> None:
    """Content smoke: brief from ICP, structured article generation, and queue placement."""

    class _PipelineResult:
        def __init__(
            self,
            *,
            detected_language: str,
            response_language: str,
            response_content: str,
            method: str,
            confidence: float,
        ) -> None:
            self.detected_language = detected_language
            self.response_language = response_language
            self.response_content = response_content
            self.method = method
            self.confidence = confidence

    class _PipelineStub:
        def process(self, user_input: str, force_language: str | None = None) -> _PipelineResult:
            language = force_language or "en"
            if "Create a JSON content brief" in user_input:
                content = (
                    '{"target_audience":"Clinic ops leaders","keywords":["manual scheduling","patient follow-up",'
                    '"workflow automation"],"tone":"practical","word_count_target":950}'
                )
            else:
                content = (
                    "# Clinic Workflow Automation Playbook\n"
                    "This guide explains a practical execution path.\n\n"
                    "## Identify Manual Bottlenecks\n"
                    "Map repetitive handoffs and failure points.\n\n"
                    "## Implement Event-Driven Routing\n"
                    "Replace copy/paste with reliable triggers and ownership.\n\n"
                    "## Track Outcomes and Iterate\n"
                    "Review cycle time, response quality, and conversion.\n\n"
                    "## Conclusion\n"
                    "Operational clarity improves speed and quality.\n\n"
                    "## CTA\n"
                    "Use ARCHON to orchestrate approvals and automation safely."
                )
            return _PipelineResult(
                detected_language=language,
                response_language=language,
                response_content=content,
                method="native_reasoning",
                confidence=0.92,
            )

    agent = ContentAgent(
        icp_agent=object(),
        vernacular_pipeline=_PipelineStub(),  # type: ignore[arg-type]
        approval_gate=None,
        publish_targets=[PublishTarget(target_id="stdout", type="stdout", config={})],
    )

    brief = agent.brief_from_icp(
        icp={
            "target_audience": "Clinic operations",
            "pain_points": ["manual scheduling", "slow follow-up"],
        },
        language_code="en",
        topic="Reducing manual scheduling overhead in clinics",
    )
    piece = agent.generate(brief)
    agent.queue.queue(piece)

    assert brief.keywords
    assert piece.title.strip()
    assert piece.body.count("## ") >= 3
    assert "## CTA" in piece.body
    assert len(agent.queue.get_queue()) == 1


def test_community_pipeline_smoke_relevant_reddit_post_composed_and_gated() -> None:
    """Community smoke: relevant manual-work post is detected, drafted, gated, and published."""

    class _StaticCollector:
        def __init__(self, posts: list[CommunityPost]) -> None:
            self.posts = list(posts)

        def collect(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            del args, kwargs
            return list(self.posts)

    class _Gate:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def check(self, action: str, context: dict[str, Any], action_id: str) -> str:
            self.calls.append({"action": action, "context": context, "action_id": action_id})
            return action_id

    post = CommunityPost(
        post_id="reddit-smoke-1",
        source="reddit",
        title="Doing this manually is painful and feels like spreadsheet hell",
        body="We still copy paste data daily. Wish there was a tool to automate this.",
        author="redditor",
        url="https://reddit.com/r/test/reddit-smoke-1",
        created_at=time.time(),
        score=12.0,
        comments=4,
    )

    detector = SignalDetector(llm_scorer=lambda _post: 0.3)
    detection = detector.detect(post)
    assert detection.is_relevant is True

    gate = _Gate()
    published: list[str] = []
    agent = CommunityAgent(
        detector=detector,
        reddit_collector=_StaticCollector([post]),
        hn_collector=_StaticCollector([]),
        rss_collector=_StaticCollector([]),
        composer=ResponseComposer(),
        approval_gate=gate,
        publisher=lambda item, draft: published.append(f"{item.post_id}:{len(draft.body)}"),
    )

    results = agent.run({"reddit": {"subreddits": ["saas"]}})
    assert len(results) == 1
    assert results[0].action_taken == "responded"
    assert results[0].approved is True
    assert gate.calls and gate.calls[0]["action"] == "send_message"
    assert len(published) == 1


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
        (None, 31),
        (None, 32),
        ("openrouter", 33),
        ("openrouter", 34),
        ("anthropic", 35),
        ("anthropic", 36),
        ("openai", 37),
        ("openai", 38),
        ("gemini", 39),
        ("gemini", 40),
        ("groq", 41),
        ("mistral", 42),
        ("together", 43),
        ("fireworks", 44),
        ("ollama", 45),
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


@pytest.mark.asyncio
async def test_billing_meter_flush_and_invoice_generation_integration() -> None:
    """Billing integration: meter usage, flush to Stripe, and generate invoice lines."""

    class _Gate:
        async def check(self, action: str, context: dict[str, object], action_id: str) -> str:
            assert action == "financial_transaction"
            assert "aggregates" in context
            return action_id

    class _Stripe:
        async def create_usage_record(
            self, subscription_item_id: str, quantity: float, timestamp: float
        ) -> StripeUsageRecord:
            return StripeUsageRecord(
                record_id=f"ur_{subscription_item_id}",
                subscription_item_id=subscription_item_id,
                quantity=quantity,
                timestamp=timestamp,
            )

    meter = UsageMeter(
        path=Path("archon/tests/_tmp_integration") / f"meter-{uuid.uuid4().hex[:8]}.sqlite3",
        approval_gate=_Gate(),
        stripe_client=_Stripe(),
    )  # type: ignore[arg-type]
    meter.record("tenant-integration", "agent_runs", 2.0, {})
    meter.record("tenant-integration", "emails_sent", 3.0, {})

    records = await meter.flush_to_stripe("tenant-integration", 0.0, time.time() + 1)
    invoice = InvoiceGenerator(meter, tier_lookup=lambda tenant_id: "pro", tax_rate=0.1).generate(
        "tenant-integration", 0.0, time.time() + 1
    )

    assert len(records) == 2
    assert {line.description for line in invoice.line_items} == {"Agent Runs", "Emails Sent"}


def test_marketplace_onboarding_flow_activates_partner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marketplace integration: onboard through API, complete Stripe checks, activate partner."""

    _set_marketplace_envs(tmp_path, monkeypatch)

    class _Stripe:
        def __init__(self) -> None:
            self.accounts: dict[str, ConnectAccount] = {}

        async def create_account(
            self, email: str, country: str, business_type: str
        ) -> ConnectAccount:
            del business_type
            account = ConnectAccount(
                account_id="acct_onboard",
                email=email,
                country=country,
                charges_enabled=False,
                payouts_enabled=False,
                details_submitted=False,
                created_at=time.time(),
            )
            self.accounts[account.account_id] = account
            return account

        async def create_account_link(
            self,
            account_id: str,
            refresh_url: str,
            return_url: str,
        ) -> str:
            del refresh_url, return_url
            return f"https://connect.example/{account_id}"

        async def get_account(self, account_id: str) -> ConnectAccount:
            return self.accounts[account_id]

    with TestClient(app) as client:
        partner = app.state.partner_registry.register(
            "Integration Partner",
            "integration@example.com",
            "affiliate",
        )
        stripe = _Stripe()
        app.state.marketplace_onboarding.stripe_client = stripe
        response = client.post(
            "/marketplace/developers/onboard",
            json={
                "partner_id": partner.partner_id,
                "email": partner.email,
                "country": "US",
            },
            headers=_auth_headers(tenant="tenant-enterprise", tier="enterprise"),
        )
        stripe.accounts["acct_onboard"] = ConnectAccount(
            account_id="acct_onboard",
            email=partner.email,
            country="US",
            charges_enabled=True,
            payouts_enabled=True,
            details_submitted=True,
            created_at=time.time(),
        )
        completed = asyncio.run(app.state.marketplace_onboarding.complete(partner.partner_id))
        refreshed = app.state.partner_registry.get(partner.partner_id)

    assert response.status_code == 200
    assert response.json()["onboarding_url"] == "https://connect.example/acct_onboard"
    assert completed is True
    assert refreshed is not None
    assert refreshed.status == "active"


def test_marketplace_revenue_cycle_records_enqueue_approve_and_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marketplace integration: record revenue, queue payout, auto-approve, execute transfer."""

    _set_marketplace_envs(tmp_path, monkeypatch)

    class _Stripe:
        async def create_transfer(
            self,
            destination_account_id: str,
            amount_usd: float,
            *,
            metadata: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            assert destination_account_id == "acct_marketplace"
            assert amount_usd >= 10.0
            assert metadata is not None
            return {"id": "tr_marketplace_1"}

    with TestClient(app) as client:
        del client
        registry = app.state.partner_registry
        ledger = app.state.marketplace_revenue_ledger
        queue = app.state.marketplace_payout_queue
        partner = registry.register("Revenue Partner", "revenue@example.com", "affiliate")
        registry.update_metadata(
            partner.partner_id, {CONNECT_ACCOUNT_METADATA_KEY: "acct_marketplace"}
        )
        registry.update_status(partner.partner_id, "active", "ready-for-payout")
        ledger.upsert_listing("listing-market", partner.partner_id, "pro_only")
        ledger.record("tenant-market", "listing-market", 100.0)
        queue.approval_gate.auto_approve_in_test = True
        queue.stripe_client = _Stripe()
        payout = queue.enqueue(partner.partner_id, 0.0, time.time() + 60.0)
        approved = asyncio.run(queue.approve(payout.payout_id))
        result = asyncio.run(queue.execute(payout.payout_id))

    assert payout is not None
    assert approved.status == "approved"
    assert result.status == "paid"
    assert result.transfer_id == "tr_marketplace_1"


def test_marketplace_earnings_api_isolates_partner_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marketplace integration: partner A cannot read partner B earnings via API."""

    _set_marketplace_envs(tmp_path, monkeypatch)

    with TestClient(app) as client:
        partner_a = app.state.partner_registry.register("Partner A", "a@example.com", "affiliate")
        partner_b = app.state.partner_registry.register("Partner B", "b@example.com", "affiliate")
        response = client.get(
            f"/marketplace/developers/{partner_b.partner_id}/earnings",
            headers=_auth_headers(tenant=partner_a.partner_id, tier="business"),
        )

    assert response.status_code == 401


def test_onprem_compose_and_validator_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """On-prem integration: GPU compose config and healthy deployment validation."""

    manifest = DockerComposeGenerator().generate(
        DeploymentConfig(
            tenant_id="tenant-onprem",
            tier="enterprise",
            enable_gpu=True,
            ollama_models=["llava:34b"],
            external_db_url="",
            smtp_host="smtp.archon.local",
            redis_url="",
            domain="archon.example",
            tls=True,
            replicas=2,
        )
    )

    class _Client:
        def get(self, url: str):  # type: ignore[no-untyped-def]
            if url.endswith("/api/tags"):
                return type(
                    "Response", (), {"status_code": 200, "json": lambda self=None: {"models": []}}
                )()
            return type(
                "Response",
                (),
                {"status_code": 200, "json": lambda self=None: {"status": "ok", "db_status": "ok"}},
            )()

        def post(self, url: str, json: dict[str, object]):  # type: ignore[no-untyped-def]
            del url, json
            return type(
                "Response", (), {"status_code": 200, "json": lambda self=None: {"token": "token"}}
            )()

    monkeypatch.setattr("archon.onprem.validator.verify_webchat_token", lambda token: {"ok": True})
    monkeypatch.setattr(
        "archon.onprem.validator._ssl_certificate_expiry",
        lambda base_url: datetime.now(timezone.utc) + timedelta(days=90),
    )
    monkeypatch.setattr(
        "archon.onprem.validator.subprocess.run",
        lambda *args, **kwargs: __import__("subprocess").CompletedProcess(
            args=args[0], returncode=0, stdout="ok", stderr=""
        ),  # type: ignore[index]
    )

    report = DeployValidator(http_client=_Client()).run_all(
        DeploymentConfig(
            tenant_id="tenant-onprem",
            tier="enterprise",
            enable_gpu=True,
            ollama_models=["llava:34b"],
            external_db_url="",
            smtp_host="smtp.archon.local",
            redis_url="",
            domain="archon.example",
            tls=True,
            replicas=2,
        ),
        "https://archon.example",
    )

    assert "ollama" in manifest.services
    assert report.blocking_failures == []


@pytest.mark.asyncio
async def test_multimodal_integration_routes_audio_and_image_to_vision_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multimodal integration: audio append + image processing + vision routing."""

    monkeypatch.setenv("OPENAI_API_KEY", "integration-openai-key")
    orchestrator = MultimodalOrchestrator(ArchonConfig())
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aN8AAAAASUVORK5CYII="
    )
    audio = _wav_bytes(1)

    async def fake_transcribe(audio_input) -> TranscriptResult:  # type: ignore[no-untyped-def]
        return TranscriptResult(
            text="integration speech", language="en", confidence=0.9, method="mock"
        )

    orchestrator.audio_processor.transcribe = fake_transcribe  # type: ignore[assignment]
    response = await orchestrator.process(
        text="inspect",
        images=[image],
        audio=[audio],
        session_id="integration-session",
        tenant_ctx={"tenant_id": "tenant-integration"},
    )

    assert response.provider == "openai"
    assert response.transcript == "integration speech"
    assert response.content


def test_studio_integration_roundtrip_save_load_deserialize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Studio integration: serialize, save via API, load back, and deserialize."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "integration-openrouter-key")
    monkeypatch.setenv(
        "ARCHON_STUDIO_DB",
        str(Path("archon/tests/_tmp_integration") / f"studio-{uuid.uuid4().hex[:8]}.sqlite3"),
    )
    nodes = [
        {
            "id": "agent-a",
            "type": "AgentNode",
            "position": {"x": 0, "y": 0},
            "data": {"agent_class": "ResearcherAgent", "action": "research"},
        },
        {
            "id": "output",
            "type": "OutputNode",
            "position": {"x": 200, "y": 0},
            "data": {"action": "emit"},
        },
    ]
    edges = [{"id": "e1", "source": "agent-a", "target": "output", "label": "text"}]
    workflow = serialize(nodes, edges)
    payload = {
        "workflow_id": workflow.workflow_id,
        "name": workflow.name,
        "steps": [
            {
                "step_id": step.step_id,
                "agent": step.agent,
                "action": step.action,
                "config": dict(step.config),
                "dependencies": list(step.dependencies),
            }
            for step in workflow.steps
        ],
        "metadata": dict(workflow.metadata),
        "version": workflow.version,
        "created_at": workflow.created_at,
    }

    with TestClient(app) as client:
        saved = client.post("/studio/workflows", json=payload, headers=_auth_headers())
        loaded = client.get(
            f"/studio/workflows/{saved.json()['workflow_id']}", headers=_auth_headers()
        )

    assert saved.status_code == 200
    assert loaded.status_code == 200
    restored = deserialize(loaded.json())
    assert restored["nodes"] == nodes
    assert restored["edges"] == edges
