"""FastAPI analytics router mounted at `/analytics`."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from archon.analytics.aggregator import AnalyticsAggregator
from archon.analytics.collector import AnalyticsCollector
from archon.api import auth as legacy_auth

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


@dataclass(slots=True, frozen=True)
class AnalyticsAccessContext:
    tenant_id: str
    tier: str

    @property
    def is_enterprise(self) -> bool:
        return self.tier == "enterprise"


def get_collector(request: Request) -> AnalyticsCollector:
    state_collector = getattr(request.app.state, "analytics_collector", None)
    if isinstance(state_collector, AnalyticsCollector):
        return state_collector
    return _DEFAULT_COLLECTOR


def get_aggregator(collector: AnalyticsCollector = Depends(get_collector)) -> AnalyticsAggregator:
    return AnalyticsAggregator(path=collector.path)


router = APIRouter(prefix="/analytics", tags=["analytics"])


def require_analytics_access(request: Request) -> AnalyticsAccessContext:
    state_auth = getattr(request.state, "auth", None)
    tenant_id = str(getattr(state_auth, "tenant_id", "")).strip()
    tier = str(getattr(state_auth, "tier", "")).strip().lower()
    if tenant_id and tier:
        return AnalyticsAccessContext(tenant_id=tenant_id, tier=tier)

    try:
        token = legacy_auth.token_from_request(request)
    except legacy_auth.TenantTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing analytics bearer token.",
        )

    try:
        context = legacy_auth.tenant_context_from_token(token)
    except legacy_auth.TenantTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return AnalyticsAccessContext(tenant_id=context.tenant_id, tier=str(context.tier))


@router.get("/summary", response_model=AnalyticsSummary)
async def analytics_summary(
    tenant_id: str = Query(min_length=1),
    days: int = Query(default=30, ge=1, le=365),
    access: AnalyticsAccessContext = Depends(require_analytics_access),
    aggregator: AnalyticsAggregator = Depends(get_aggregator),
) -> AnalyticsSummary:
    _authorize_tenant_scope(access=access, requested_tenant_id=tenant_id)

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
    access: AnalyticsAccessContext = Depends(require_analytics_access),
    aggregator: AnalyticsAggregator = Depends(get_aggregator),
) -> list[dict[str, Any]]:
    _authorize_tenant_scope(access=access, requested_tenant_id=tenant_id)
    return aggregator.timeseries(tenant_id=tenant_id, metric=str(metric), days=days)


@router.get("/events")
async def analytics_events(
    tenant_id: str = Query(min_length=1),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    access: AnalyticsAccessContext = Depends(require_analytics_access),
    aggregator: AnalyticsAggregator = Depends(get_aggregator),
) -> list[dict[str, Any]]:
    _authorize_tenant_scope(access=access, requested_tenant_id=tenant_id)
    return aggregator.raw_events(tenant_id=tenant_id, event_type=event_type, limit=limit)


@router.get("/leaderboard")
async def analytics_leaderboard(
    tenant_id: str | None = Query(default=None),
    scope: str = Query(default="tenant", pattern="^(tenant|global)$"),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=100),
    access: AnalyticsAccessContext = Depends(require_analytics_access),
    aggregator: AnalyticsAggregator = Depends(get_aggregator),
) -> list[dict[str, Any]]:
    period_end = time.time()
    period_start = period_end - (int(days) * 86400)

    if scope == "global":
        if not access.is_enterprise:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Enterprise tier required for global benchmark access.",
            )
        return aggregator.agent_leaderboard(
            period_start,
            period_end,
            limit=limit,
            tenant_id=None,
            viewer_tenant_id=access.tenant_id,
        )

    requested_tenant_id = str(tenant_id or access.tenant_id).strip()
    _authorize_tenant_scope(access=access, requested_tenant_id=requested_tenant_id)
    return aggregator.agent_leaderboard(
        period_start,
        period_end,
        limit=limit,
        tenant_id=requested_tenant_id,
        viewer_tenant_id=access.tenant_id,
    )


@router.post("/events")
async def analytics_events_batch(
    payload: list[AnalyticsEventInput],
    access: AnalyticsAccessContext = Depends(require_analytics_access),
    collector: AnalyticsCollector = Depends(get_collector),
) -> dict[str, Any]:
    if not access.is_enterprise:
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


def _authorize_tenant_scope(*, access: AnalyticsAccessContext, requested_tenant_id: str) -> None:
    if access.is_enterprise:
        return
    if access.tenant_id != requested_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch.")
