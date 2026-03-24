"""Observability coverage for tracing and metrics helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from archon.observability.metrics import Metrics
from archon.observability.setup import configure_observability
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
        cost_optimizer = None

        async def execute(self, **kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                mode=kwargs.get("mode", "debate"),
                budget={"spent_usd": 0.25, "budget_usd": 1.0},
            )

    orchestrator = _FakeOrchestrator()
    TracingSetup.configure(service_name="archon-test")
    TracingSetup.instrument_orchestrator(orchestrator)

    result = await orchestrator.execute(mode="debate", context={"tenant_id": "tenant-z"})

    assert result.mode == "debate"
    spans = TracingSetup.list_spans(limit=5)
    orchestrator_span = spans[-1]
    assert orchestrator_span["name"] == "orchestrator.run"
    assert orchestrator_span["attributes"]["tenant_id"] == "tenant-z"
    assert orchestrator_span["attributes"]["mode"] == "debate"
    assert orchestrator_span["attributes"]["cost_usd"] == 0.25


def test_metrics_counter_increments_work_in_noop_mode() -> None:
    Metrics.reset_for_tests(force_noop=True)
    metrics = Metrics.get_instance()

    metrics.increment_request(method="GET", path="/health", status=200)
    text = metrics.render_prometheus_text()

    assert "archon_requests_total" in text
    assert 'path="/health"' in text


def test_configure_observability_announces_ascii_status_lines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    Metrics.reset_for_tests(force_noop=True)
    TracingSetup.reset_for_tests(force_noop=True)
    test_app = FastAPI()

    configure_observability(test_app)

    output = capsys.readouterr().out
    assert "Metrics  -> http://127.0.0.1:8000/metrics" in output
    assert "Traces   -> http://127.0.0.1:8000/observability/traces" in output
    assert "Grafana  -> docker compose -f docker-compose.observability.yml up" in output
    assert "✔" not in output
    assert "→" not in output
