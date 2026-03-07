"""Observability coverage for tracing, metrics, and CLI surfaces."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from archon.archon_cli import cli
from archon.interfaces.api.server import app
from archon.observability.metrics import Metrics
from archon.observability.tracing import TracingSetup


def test_tracing_configure_returns_tracer_without_opentelemetry() -> None:
    TracingSetup.reset_for_tests(force_noop=True)
    tracer = TracingSetup.configure(service_name="archon-test")
    with tracer.start_as_current_span("noop.span") as span:
        span.set_attribute("tenant_id", "tenant-a")

    spans = TracingSetup.list_spans(limit=5)
    assert tracer is not None
    assert spans[-1]["name"] == "noop.span"
    assert spans[-1]["attributes"]["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_tracing_records_mocked_orchestrator_span_attributes() -> None:
    TracingSetup.reset_for_tests(force_noop=True)
    Metrics.reset_for_tests(force_noop=True)

    class _FakeOrchestrator:
        provider_router = None
        approval_gate = None
        swarm_router = None
        growth_router = None
        email_agent = None
        webchat_agent = None

        async def execute(self, **kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                mode=kwargs.get("mode", "debate"),
                budget={"spent_usd": 0.25, "budget_usd": 1.0},
            )

    orchestrator = _FakeOrchestrator()
    TracingSetup.configure(service_name="archon-test")
    TracingSetup.instrument_orchestrator(orchestrator)

    result = await orchestrator.execute(mode="growth", context={"tenant_id": "tenant-z"})

    assert result.mode == "growth"
    spans = TracingSetup.list_spans(limit=5)
    orchestrator_span = spans[-1]
    assert orchestrator_span["name"] == "orchestrator.run"
    assert orchestrator_span["attributes"]["tenant_id"] == "tenant-z"
    assert orchestrator_span["attributes"]["mode"] == "growth"
    assert orchestrator_span["attributes"]["cost_usd"] == 0.25


def test_traces_endpoint_returns_list_shape() -> None:
    TracingSetup.reset_for_tests(force_noop=True)
    Metrics.reset_for_tests(force_noop=True)
    tracer = TracingSetup.configure(service_name="archon-test")
    with tracer.start_as_current_span("endpoint.span"):
        pass

    with TestClient(app) as client:
        response = client.get("/observability/traces")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)


def test_metrics_counter_increments_work_in_noop_mode() -> None:
    Metrics.reset_for_tests(force_noop=True)
    metrics = Metrics.get_instance()

    metrics.increment_request(method="GET", path="/health", status=200)
    text = metrics.render_prometheus_text()

    assert "archon_requests_total" in text
    assert 'path="/health"' in text


def test_metrics_endpoint_returns_plaintext() -> None:
    Metrics.reset_for_tests(force_noop=True)
    TracingSetup.reset_for_tests(force_noop=True)

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


def test_metrics_middleware_increments_request_counter_on_each_request() -> None:
    Metrics.reset_for_tests(force_noop=True)
    TracingSetup.reset_for_tests(force_noop=True)

    with TestClient(app) as client:
        client.get("/health")
        client.get("/health")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert 'archon_requests_total{method="GET",path="/health",status="200"}' in response.text


def test_cli_metrics_command_renders_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics_payload = """
# HELP archon_requests_total Total ARCHON HTTP requests.
archon_requests_total{method="GET",path="/health",status="200"} 12
archon_active_sessions 3
archon_pending_approvals 1
archon_llm_calls_total{provider="openai",model="gpt-4o"} 9
"""

    monkeypatch.setattr("archon.archon_cli._request_text", lambda method, url, **kwargs: metrics_payload)
    runner = CliRunner()
    result = runner.invoke(cli, ["metrics"])

    assert result.exit_code == 0
    assert "requests" in result.output.lower()
    assert "sessions" in result.output.lower()


def test_cli_traces_command_renders_span_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "archon.archon_cli._request_json",
        lambda method, url, **kwargs: [
            {
                "span_id": "1",
                "parent_id": None,
                "name": "orchestrator.run",
                "status": "ok",
                "duration_ms": 10.0,
            },
            {
                "span_id": "2",
                "parent_id": "1",
                "name": "llm.call",
                "status": "ok",
                "duration_ms": 2.0,
            },
        ],
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["traces"])

    assert result.exit_code == 0
    assert "orchestrator.run" in result.output
    assert "llm.call" in result.output


def test_cli_monitor_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "archon.archon_cli._request_json",
        lambda method, url, **kwargs: (
            {"status": "ok", "version": "0.1.0"}
            if url.endswith("/health")
            else [{"span_id": "1", "parent_id": None, "name": "agent.run", "status": "ok", "duration_ms": 1.0}]
        ),
    )
    monkeypatch.setattr(
        "archon.archon_cli._request_text",
        lambda method, url, **kwargs: """
archon_requests_total{method="GET",path="/health",status="200"} 10
archon_active_sessions 2
archon_pending_approvals 0
archon_agents_recruited_total{agent_name="ResearcherAgent"} 4
""",
    )
    monkeypatch.setattr("archon.archon_cli._clear_monitor_screen", lambda: None)

    def _stop(_seconds: float) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr("archon.archon_cli._monitor_sleep", _stop)

    runner = CliRunner()
    result = runner.invoke(cli, ["monitor", "--interval", "0.1"])

    assert result.exit_code == 0
    assert "Monitor stopped." in result.output
