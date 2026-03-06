"""FastAPI analytics router mounted at `/analytics`."""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from archon.analytics.aggregator import AnalyticsAggregator
from archon.analytics.collector import AnalyticsCollector
from archon.api.auth import TenantContext, require_tenant

_DEFAULT_DB_PATH = os.getenv("ARCHON_ANALYTICS_DB", "archon_analytics.sqlite3")
_DEFAULT_COLLECTOR = AnalyticsCollector(path=_DEFAULT_DB_PATH)


class AnalyticsSummary(BaseModel):
    total_sessions: int
    total_cost_usd: float
    approval_rate: float
    top_agents: list[dict[str, Any]]
    cost_by_provider: dict[str, float]


class AnalyticsEventInput(BaseModel):
    tenant_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)
    event_id: str | None = None
    timestamp: float | None = None


def get_collector() -> AnalyticsCollector:
    return _DEFAULT_COLLECTOR


def get_aggregator(collector: AnalyticsCollector = Depends(get_collector)) -> AnalyticsAggregator:
    return AnalyticsAggregator(path=collector.path)


router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
async def analytics_summary(
    tenant_id: str = Query(min_length=1),
    days: int = Query(default=30, ge=1, le=365),
    tenant: TenantContext = Depends(require_tenant),
    aggregator: AnalyticsAggregator = Depends(get_aggregator),
) -> AnalyticsSummary:
    _authorize_tenant_scope(tenant=tenant, requested_tenant_id=tenant_id)

    period_end = time.time()
    period_start = period_end - (int(days) * 86400)

    cost_map = aggregator.cost_by_provider(tenant_id, period_start, period_end)
    total_cost = round(sum(cost_map.values()), 6)
    return AnalyticsSummary(
        total_sessions=aggregator.total_sessions(tenant_id, period_start, period_end),
        total_cost_usd=total_cost,
        approval_rate=aggregator.approval_rate(tenant_id, period_start, period_end),
        top_agents=aggregator.top_agents(tenant_id, period_start, period_end),
        cost_by_provider=cost_map,
    )


@router.get("/timeseries")
async def analytics_timeseries(
    tenant_id: str = Query(min_length=1),
    metric: str = Query(default="total_cost_usd", min_length=1),
    days: int = Query(default=30, ge=1, le=365),
    tenant: TenantContext = Depends(require_tenant),
    aggregator: AnalyticsAggregator = Depends(get_aggregator),
) -> list[dict[str, Any]]:
    _authorize_tenant_scope(tenant=tenant, requested_tenant_id=tenant_id)
    return aggregator.timeseries(tenant_id=tenant_id, metric=str(metric), days=days)


@router.get("/events")
async def analytics_events(
    tenant_id: str = Query(min_length=1),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    tenant: TenantContext = Depends(require_tenant),
    aggregator: AnalyticsAggregator = Depends(get_aggregator),
) -> list[dict[str, Any]]:
    _authorize_tenant_scope(tenant=tenant, requested_tenant_id=tenant_id)
    return aggregator.raw_events(tenant_id=tenant_id, event_type=event_type, limit=limit)


@router.post("/events")
async def analytics_events_batch(
    payload: list[AnalyticsEventInput],
    tenant: TenantContext = Depends(require_tenant),
    collector: AnalyticsCollector = Depends(get_collector),
) -> dict[str, Any]:
    if tenant.tier != "enterprise":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Enterprise tier required for analytics batch ingest.",
        )

    records = collector.batch_record([item.model_dump() for item in payload])
    return {
        "status": "ok",
        "count": len(records),
        "event_ids": [row.event_id for row in records],
    }


def create_router() -> APIRouter:
    """Factory helper for mounting the analytics router."""

    return router


def _authorize_tenant_scope(*, tenant: TenantContext, requested_tenant_id: str) -> None:
    if tenant.tier == "enterprise":
        return
    if tenant.tenant_id != requested_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch.")
