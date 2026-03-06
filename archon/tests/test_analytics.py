"""Tests for analytics collector, aggregations, and dashboard API router."""

from __future__ import annotations

import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from archon.analytics.aggregator import AnalyticsAggregator
from archon.analytics.collector import AnalyticsCollector
from archon.analytics.dashboard_api import create_router, get_aggregator, get_collector
from archon.api import auth as auth_module


def _tmp_db(name: str) -> Path:
    root = Path("archon/tests/_tmp_analytics")
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{name}-{uuid.uuid4().hex[:8]}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "analytics.sqlite3"


def _token(tenant_id: str, tier: str = "pro") -> str:
    return auth_module.create_tenant_token(tenant_id, tier, secret="test-secret")


def _headers(tenant_id: str, tier: str = "pro") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(tenant_id, tier=tier)}"}


def _build_app(db_path: Path) -> tuple[FastAPI, AnalyticsCollector, AnalyticsAggregator]:
    app = FastAPI()
    collector = AnalyticsCollector(path=db_path)
    aggregator = AnalyticsAggregator(path=db_path)
    app.include_router(create_router())
    app.dependency_overrides[get_collector] = lambda: collector
    app.dependency_overrides[get_aggregator] = lambda: aggregator
    return app, collector, aggregator


def test_collector_record_batch_and_append_only_with_tenant_isolation() -> None:
    db_path = _tmp_db("collector")
    collector = AnalyticsCollector(path=db_path)

    first = collector.record("tenant-a", "session_started", {"session_id": "s-1"})
    batch = collector.batch_record(
        [
            {
                "tenant_id": "tenant-a",
                "event_type": "message_sent",
                "properties": {"session_id": "s-1", "channel": "webchat"},
            },
            {
                "tenant_id": "tenant-b",
                "event_type": "message_sent",
                "properties": {"session_id": "s-b"},
            },
        ]
    )

    assert first.event_id
    assert len(batch) == 2
    assert not hasattr(collector, "update")
    assert not hasattr(collector, "delete")

    aggregator = AnalyticsAggregator(path=db_path)
    tenant_a_rows = aggregator.raw_events("tenant-a", limit=10)
    assert tenant_a_rows
    assert all(row["tenant_id"] == "tenant-a" for row in tenant_a_rows)
    assert all(row["tenant_id"] != "tenant-b" for row in tenant_a_rows)


def test_aggregator_metrics_daily_cost_approval_and_swarm_efficiency() -> None:
    db_path = _tmp_db("aggregator")
    collector = AnalyticsCollector(path=db_path)

    now = time.time()
    collector.batch_record(
        [
            {
                "tenant_id": "tenant-a",
                "event_type": "session_started",
                "timestamp": now - 10,
                "properties": {"session_id": "s-1"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "session_started",
                "timestamp": now - 9,
                "properties": {"session_id": "s-2"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "cost_incurred",
                "timestamp": now - 8,
                "properties": {"provider": "openai", "cost_usd": 1.25, "session_id": "s-1"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "cost_incurred",
                "timestamp": now - 7,
                "properties": {"provider": "openai", "cost_usd": 0.75, "session_id": "s-1"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "cost_incurred",
                "timestamp": now - 6,
                "properties": {"provider": "together", "cost_usd": 2.0, "session_id": "s-2"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "approval_granted",
                "timestamp": now - 5,
                "properties": {"session_id": "s-1"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "approval_granted",
                "timestamp": now - 4,
                "properties": {"session_id": "s-1"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "approval_granted",
                "timestamp": now - 3,
                "properties": {"session_id": "s-2"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "approval_denied",
                "timestamp": now - 2,
                "properties": {"session_id": "s-2"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "agent_recruited",
                "timestamp": now - 2,
                "properties": {
                    "task_id": "task-1",
                    "agent": "ProspectorAgent",
                    "session_id": "s-1",
                },
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "agent_recruited",
                "timestamp": now - 1.5,
                "properties": {"task_id": "task-1", "agent": "ICPAgent", "session_id": "s-1"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "agent_recruited",
                "timestamp": now - 1,
                "properties": {"task_id": "task-2", "agent": "OutreachAgent", "session_id": "s-2"},
            },
        ]
    )

    aggregator = AnalyticsAggregator(path=db_path)
    today = datetime.now(tz=timezone.utc).date()
    assert aggregator.daily_active_sessions("tenant-a", today) == 2

    start, end = now - 60, now + 60
    costs = aggregator.cost_by_provider("tenant-a", start, end)
    assert costs["openai"] == 2.0
    assert costs["together"] == 2.0

    assert aggregator.approval_rate("tenant-a", start, end) == 0.75
    assert aggregator.swarm_efficiency("tenant-a", start, end) == 1.5


def test_dashboard_api_auth_mismatch_timeseries_and_limit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ARCHON_JWT_SECRET", "test-secret")
    auth_module.set_rate_limiter(auth_module.RateLimiter())

    db_path = _tmp_db("api")
    app, collector, _aggregator = _build_app(db_path)

    now = time.time()
    collector.batch_record(
        [
            {
                "tenant_id": "tenant-a",
                "event_type": "session_started",
                "timestamp": now - 30,
                "properties": {"session_id": "s-1"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "cost_incurred",
                "timestamp": now - 20,
                "properties": {"provider": "openai", "cost_usd": 3.0, "session_id": "s-1"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "message_sent",
                "timestamp": now - 10,
                "properties": {"session_id": "s-1"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "message_sent",
                "timestamp": now - 9,
                "properties": {"session_id": "s-1"},
            },
            {
                "tenant_id": "tenant-a",
                "event_type": "message_sent",
                "timestamp": now - 8,
                "properties": {"session_id": "s-1"},
            },
        ]
    )

    with TestClient(app) as client:
        unauth = client.get("/analytics/summary", params={"tenant_id": "tenant-a", "days": 30})
        assert unauth.status_code == 401

        mismatch = client.get(
            "/analytics/summary",
            params={"tenant_id": "tenant-b", "days": 30},
            headers=_headers("tenant-a", tier="pro"),
        )
        assert mismatch.status_code == 403

        enterprise_ok = client.get(
            "/analytics/summary",
            params={"tenant_id": "tenant-a", "days": 30},
            headers=_headers("ops-root", tier="enterprise"),
        )
        assert enterprise_ok.status_code == 200

        series = client.get(
            "/analytics/timeseries",
            params={"tenant_id": "tenant-a", "metric": "total_cost_usd", "days": 3},
            headers=_headers("tenant-a", tier="pro"),
        )
        assert series.status_code == 200
        payload = series.json()
        assert isinstance(payload, list)
        assert payload
        assert "date" in payload[0]
        assert "value" in payload[0]

        limited = client.get(
            "/analytics/events",
            params={"tenant_id": "tenant-a", "limit": 2},
            headers=_headers("tenant-a", tier="pro"),
        )
        assert limited.status_code == 200
        rows = limited.json()
        assert isinstance(rows, list)
        assert len(rows) == 2
