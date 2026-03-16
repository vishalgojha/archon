"""One-shot observability bootstrap for the ARCHON API."""

from __future__ import annotations

import os
from typing import Any

from archon.observability.metrics import Metrics
from archon.observability.tracing import TracingSetup

_OBSERVABILITY_ANNOUNCEMENTS = (
    "Metrics  -> http://127.0.0.1:8000/metrics",
    "Traces   -> http://127.0.0.1:8000/observability/traces",
    "Grafana  -> docker compose -f docker-compose.observability.yml up",
)


def configure_observability(app: Any) -> None:
    """Configure tracing, metrics, and instrumentation for a FastAPI app."""

    metrics = Metrics.get_instance()
    tracer = TracingSetup.configure(
        service_name=os.getenv("ARCHON_SERVICE_NAME", "archon"),
        otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
    )
    TracingSetup.instrument_fastapi(app)
    orchestrator = getattr(getattr(app, "state", None), "orchestrator", None)
    if orchestrator is not None:
        TracingSetup.instrument_orchestrator(orchestrator)
    metrics.refresh_runtime_gauges(app)
    app.state.metrics = metrics
    app.state.tracing = tracer
    if not bool(getattr(app.state, "_archon_observability_announced", False)):
        for line in _OBSERVABILITY_ANNOUNCEMENTS:
            print(line)
        app.state._archon_observability_announced = True
