"""FastAPI server entrypoint for ARCHON runtime APIs."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import os
import signal
import socket
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, cast

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from starlette.responses import FileResponse, PlainTextResponse, Response, StreamingResponse

from archon.analytics import AnalyticsCollector
from archon.analytics.dashboard_api import create_router as create_analytics_router
from archon.billing import (
    BillingService,
    BillingStore,
    InvoiceGenerator,
    StripeClient,
    StripeGateway,
    StripeWebhookHandler,
    StripeWebhookVerifier,
    UsageMeter,
    create_webhook_router,
)
from archon.config import load_archon_config
from archon.core.approval_gate import ApprovalDeniedError, ApprovalRequiredError
from archon.core.orchestrator import OrchestrationResult, Orchestrator
from archon.evolution.engine import Step, WorkflowDefinition
from archon.interfaces.api.auth import AuthMiddleware, AuthSettings, websocket_auth_context
from archon.interfaces.api.billing_api import create_router as create_billing_router
from archon.interfaces.api.rate_limit import (
    InMemoryTierRateLimitStore,
    create_limiter,
    limit_for_key,
    set_rate_limit_store,
)
from archon.interfaces.webchat.server import mount_webchat
from archon.marketplace import DeveloperOnboarding, StripeConnectClient
from archon.marketplace.payout_orchestrator import PartnerRevenueReport, PayoutOrchestrator
from archon.marketplace.revenue_share import PayoutQueue, RevenueShareLedger
from archon.mobile.sync_store import MobileSyncStore
from archon.notifications.approval_notifier import wrap_gate
from archon.notifications.device_registry import DeviceRegistry
from archon.notifications.push import PushNotifier
from archon.observability.metrics import Metrics
from archon.observability.setup import configure_observability
from archon.observability.tracing import TracingSetup
from archon.partners.registry import PartnerRegistry
from archon.providers.router import DEFAULT_BASE_URL, PROVIDER_ENV_KEY
from archon.studio.runtime import WorkflowRunBroker, execute_workflow_run
from archon.studio.store import StudioWorkflowStore
from archon.studio.workflow_serializer import validate as validate_studio_workflow
from archon.web.injection_generator import InjectionGenerator
from archon.web.intent_classifier import IntentClassifier, SiteIntent
from archon.web.site_crawler import SiteCrawler


class TaskRequest(BaseModel):
    """Task request accepted by HTTP and WebSocket APIs."""

    goal: str = Field(min_length=1)
    mode: Literal["debate", "growth"] = "debate"
    language: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    """JSON-safe API response for completed orchestration tasks."""

    task_id: str
    goal: str
    mode: Literal["debate", "growth"]
    final_answer: str
    confidence: int
    budget: dict[str, Any]
    debate: dict[str, Any] | None = None
    growth: dict[str, Any] | None = None


class ApprovalActionRequest(BaseModel):
    """Payload for approving or denying a pending guarded action."""

    approver: str | None = None
    notes: str | None = None


class EmailOutboundRequest(BaseModel):
    """Payload for outbound email execution."""

    to_email: str = Field(min_length=3)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    from_email: str | None = None
    reply_to: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    auto_approve: bool = False


class EmailOutboundResponse(BaseModel):
    """Response for outbound email execution."""

    status: str
    result: dict[str, Any]


class WebChatOutboundRequest(BaseModel):
    """Payload for outbound webchat message execution."""

    session_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    auto_approve: bool = False


class WebChatOutboundResponse(BaseModel):
    """Response for outbound webchat message execution."""

    status: str
    result: dict[str, Any]


class ConsoleAgentUpdateRequest(BaseModel):
    """Payload for updating one agent Python file."""

    content: str = Field(default="")


class ConsoleProviderSecret(BaseModel):
    """Provider secret mutation payload."""

    api_key: str | None = None


class ConsoleBudgetConfig(BaseModel):
    """Budget settings payload for console config."""

    daily_limit_usd: float | None = None
    monthly_limit_usd: float | None = None
    per_request_limit_usd: float | None = None


class ConsoleConfigRequest(BaseModel):
    """Tenant-scoped console config payload."""

    providers: dict[str, ConsoleProviderSecret] = Field(default_factory=dict)
    budget: ConsoleBudgetConfig = Field(default_factory=ConsoleBudgetConfig)


class ConsoleCrawlRequest(BaseModel):
    """Console crawl + embed generation payload."""

    url: str = Field(min_length=1)
    api_key: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class FederationTaskRequest(BaseModel):
    """Federated task payload exchanged between ARCHON peers."""

    task_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required_capabilities: list[str] = Field(default_factory=list)
    requester_instance_id: str = Field(min_length=1)
    deadline_s: float = Field(default=30.0, gt=0.0)
    context: dict[str, Any] = Field(default_factory=dict)


class StudioWorkflowRequest(BaseModel):
    """Payload for storing one Studio workflow definition."""

    workflow_id: str | None = None
    name: str = Field(min_length=1)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    version: int = Field(default=1, ge=1)
    created_at: float | None = None


class StudioRunRequest(BaseModel):
    """Payload for executing one Studio workflow definition."""

    workflow: dict[str, Any]


class MarketplaceOnboardRequest(BaseModel):
    """Payload for starting developer Stripe Connect onboarding."""

    partner_id: str = Field(min_length=1)
    email: str = Field(min_length=3)
    country: str = Field(default="US", min_length=2, max_length=2)


class MarketplaceRunCycleRequest(BaseModel):
    """Payload for manually running a marketplace payout cycle."""

    period: str | None = None
    period_start: float | None = None
    period_end: float | None = None
    auto_approve: bool = False


def _to_response(result: OrchestrationResult) -> TaskResponse:
    return TaskResponse(
        task_id=result.task_id,
        goal=result.goal,
        mode=result.mode,
        final_answer=result.final_answer,
        confidence=result.confidence,
        budget=result.budget,
        debate=result.debate,
        growth=result.growth,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_path = os.getenv("ARCHON_CONFIG", "config.archon.yaml")
    app.state.orchestrator = Orchestrator(load_archon_config(config_path))
    app.state.auth_settings = AuthSettings.from_env()
    app.state.analytics_collector = AnalyticsCollector(
        path=os.getenv("ARCHON_ANALYTICS_DB", "archon_analytics.sqlite3")
    )
    app.state.mobile_sync_store = MobileSyncStore(
        path=os.getenv("ARCHON_MOBILE_SYNC_DB", "archon_mobile_sync.sqlite3")
    )
    app.state.mobile_device_registry = DeviceRegistry(
        path=os.getenv("ARCHON_DEVICE_TOKENS_DB", "archon_device_tokens.sqlite3")
    )
    stripe_api_key = os.getenv("ARCHON_STRIPE_SECRET_KEY", "") or os.getenv("STRIPE_SECRET_KEY", "")
    webhook_secret = os.getenv("ARCHON_STRIPE_WEBHOOK_SECRET", "") or os.getenv(
        "STRIPE_WEBHOOK_SECRET", ""
    )
    stripe_live_mode = str(os.getenv("ARCHON_STRIPE_LIVE_MODE", "")).strip().lower() == "true"
    app.state.stripe_client = StripeClient(
        secret_key=stripe_api_key,
        webhook_secret=webhook_secret,
    )
    app.state.billing_service = BillingService(
        store=BillingStore(path=os.getenv("ARCHON_BILLING_DB", "archon_billing.sqlite3")),
        approval_gate=app.state.orchestrator.approval_gate,
        collector=app.state.analytics_collector,
        gateway=StripeGateway(api_key=stripe_api_key, live_mode=stripe_live_mode),
        webhook_verifier=(
            StripeWebhookVerifier(webhook_secret) if str(webhook_secret).strip() else None
        ),
    )
    app.state.usage_meter = UsageMeter(
        path=os.getenv("ARCHON_USAGE_METER_DB", "archon_metering.sqlite3"),
        stripe_client=app.state.stripe_client,
        approval_gate=app.state.orchestrator.approval_gate,
    )
    app.state.invoice_generator = InvoiceGenerator(
        app.state.usage_meter,
        tier_lookup=lambda tenant_id: _billing_tier_for_tenant(app, tenant_id),
    )
    app.state.stripe_webhook_handler = StripeWebhookHandler(
        stripe_client=app.state.stripe_client,
        billing_service=app.state.billing_service,
        collector=app.state.analytics_collector,
    )
    app.state.studio_store = StudioWorkflowStore(
        path=os.getenv("ARCHON_STUDIO_DB", "archon_studio.sqlite3")
    )
    app.state.studio_run_broker = WorkflowRunBroker()
    app.state.partner_registry = PartnerRegistry(
        path=os.getenv("ARCHON_PARTNERS_DB", "archon_partners.sqlite3")
    )
    marketplace_revenue_db = os.getenv(
        "ARCHON_MARKETPLACE_REVENUE_DB",
        "archon_marketplace_revenue.sqlite3",
    )
    app.state.marketplace_stripe_client = StripeConnectClient(secret_key=stripe_api_key)
    app.state.marketplace_onboarding = DeveloperOnboarding(
        registry=app.state.partner_registry,
        stripe_client=app.state.marketplace_stripe_client,
        path=os.getenv(
            "ARCHON_MARKETPLACE_CONNECT_DB",
            "archon_marketplace_connect.sqlite3",
        ),
    )
    app.state.marketplace_revenue_ledger = RevenueShareLedger(
        registry=app.state.partner_registry,
        path=marketplace_revenue_db,
    )
    app.state.marketplace_payout_queue = PayoutQueue(
        registry=app.state.partner_registry,
        ledger=app.state.marketplace_revenue_ledger,
        approval_gate=app.state.orchestrator.approval_gate,
        stripe_client=app.state.marketplace_stripe_client,
        path=marketplace_revenue_db,
    )
    app.state.marketplace_payout_orchestrator = PayoutOrchestrator(
        registry=app.state.partner_registry,
        ledger=app.state.marketplace_revenue_ledger,
        payout_queue=app.state.marketplace_payout_queue,
        approval_gate=app.state.orchestrator.approval_gate,
        path=os.getenv(
            "ARCHON_MARKETPLACE_CYCLE_DB",
            "archon_marketplace_cycles.sqlite3",
        ),
    )
    app.state.marketplace_revenue_report = PartnerRevenueReport(
        ledger=app.state.marketplace_revenue_ledger,
        payout_queue=app.state.marketplace_payout_queue,
    )
    app.state.mobile_push_notifier = PushNotifier(
        registry=app.state.mobile_device_registry,
        approval_gate=app.state.orchestrator.approval_gate,
    )
    wrap_gate(
        app.state.orchestrator.approval_gate,
        app.state.mobile_device_registry,
        app.state.mobile_push_notifier,
        sync_store=app.state.mobile_sync_store,
    )
    app.state.started_monotonic = time.monotonic()
    if not isinstance(getattr(app.state, "console_tenant_config", None), dict):
        app.state.console_tenant_config = {}
    if getattr(app.state, "webchat_app", None) is not None:
        app.state.webchat_app.state.runtime.orchestrator = app.state.orchestrator
        app.state.webchat_app.state.runtime.analytics_collector = app.state.analytics_collector
        app.state.webchat_app.state.runtime.mobile_sync_store = app.state.mobile_sync_store
        app.state.webchat_app.state.runtime.device_registry = app.state.mobile_device_registry
        app.state.webchat_app.state.runtime.push_notifier = app.state.mobile_push_notifier
    configure_observability(app)
    try:
        yield
    finally:
        marketplace_stripe_client = getattr(app.state, "marketplace_stripe_client", None)
        if marketplace_stripe_client is not None and callable(
            getattr(marketplace_stripe_client, "aclose", None)
        ):
            await marketplace_stripe_client.aclose()
        stripe_client = getattr(app.state, "stripe_client", None)
        if stripe_client is not None and callable(getattr(stripe_client, "aclose", None)):
            await stripe_client.aclose()
        billing_service = getattr(app.state, "billing_service", None)
        if isinstance(billing_service, BillingService) and billing_service.gateway is not None:
            await billing_service.gateway.aclose()
        await app.state.orchestrator.aclose()


app = FastAPI(title="ARCHON API", version="0.1.0", lifespan=lifespan)
EXEMPT_PREFIXES = {
    "/webchat",
    "/health",
    "/metrics",
    "/observability",
    "/docs",
    "/openapi.json",
    "/federation",
}
_exempt_paths = {
    "/health",
    "/healthz",
    "/memory/timeline",
    "/agents/status",
    "/dashboard",
    "/dashboard/",
    "/metrics",
    "/observability/traces",
    "/studio",
    "/studio/",
    "/webchat",
    "/webchat/token",
    "/webchat/upgrade",
    "/billing/webhooks/stripe",
    "/v1/billing/webhooks/stripe",
    "/openapi.json",
    "/docs",
    "/redoc",
}
_exempt_path_prefixes = {
    "/dashboard/src",
    "/studio/assets",
    "/webchat/static",
    *EXEMPT_PREFIXES,
}
app.add_middleware(
    AuthMiddleware,
    settings=AuthSettings.from_env(),
    exempt_paths=_exempt_paths,
    exempt_path_prefixes=_exempt_path_prefixes,
)

limiter = create_limiter()
app.state.limiter = limiter
app.state.rate_limit_store = InMemoryTierRateLimitStore.from_env()
set_rate_limit_store(app.state.rate_limit_store)
app.state.started_monotonic = time.monotonic()
app.state.console_tenant_config = {}
app.state.webchat_app = None
_studio_static_dir = Path(__file__).resolve().parents[1] / "web" / "studio"
_dashboard_static_dir = Path(__file__).resolve().parents[1] / "web" / "dashboard"
if _studio_static_dir.exists():
    app.mount(
        "/studio/assets", StaticFiles(directory=str(_studio_static_dir)), name="studio-assets"
    )
if (_dashboard_static_dir / "src").exists():
    app.mount(
        "/dashboard/src",
        StaticFiles(directory=str(_dashboard_static_dir / "src")),
        name="dashboard-src",
    )
_rate_limit_handler = cast(
    Callable[[Request, Exception], Response],
    _rate_limit_exceeded_handler,
)
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.include_router(create_billing_router())
app.include_router(create_analytics_router())
app.include_router(create_webhook_router())


@app.middleware("http")
async def observability_http_metrics(request: Request, call_next):
    """Record HTTP request metrics for every API request."""

    started = time.perf_counter()
    status_code = 500
    metrics = Metrics.get_instance()
    try:
        response = await call_next(request)
        status_code = int(getattr(response, "status_code", 200) or 200)
        return response
    finally:
        path = _observability_path_label(request)
        duration = max(0.0, time.perf_counter() - started)
        metrics.increment_request(method=request.method, path=path, status=status_code)
        metrics.observe_request_duration(path=path, duration_seconds=duration)


@app.get("/studio", include_in_schema=False)
@app.get("/studio/", include_in_schema=False)
async def studio_index() -> Response:
    """Serve the standalone Studio application shell."""

    if not _studio_static_dir.exists():
        raise HTTPException(status_code=404, detail="Studio UI is unavailable.")
    return FileResponse(_studio_static_dir / "index.html")


@app.get("/dashboard", include_in_schema=False)
@app.get("/dashboard/", include_in_schema=False)
async def dashboard_index() -> Response:
    """Serve the Mission Control dashboard shell."""

    if not _dashboard_static_dir.exists():
        raise HTTPException(status_code=404, detail="Dashboard UI is unavailable.")
    return FileResponse(_dashboard_static_dir / "index.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    """Runtime health with version and uptime."""

    started = float(getattr(app.state, "started_monotonic", time.monotonic()))
    return {
        "status": "ok",
        "db_status": "ok",
        "version": app.version,
        "uptime_s": max(0.0, time.monotonic() - started),
    }


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    """Simple readiness probe endpoint."""

    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> PlainTextResponse:
    """Expose Prometheus-compatible metrics for local/dev scraping."""

    metrics = Metrics.get_instance()
    metrics.refresh_runtime_gauges(app)
    return PlainTextResponse(
        metrics.render_prometheus_text(),
        media_type=metrics.content_type,
    )


@app.get("/observability/traces", include_in_schema=False)
async def traces_endpoint(limit: int = 100, failed: bool = False) -> list[dict[str, Any]]:
    """Expose recent in-memory spans for local trace inspection."""

    return TracingSetup.list_spans(limit=max(1, min(500, int(limit))), failed_only=bool(failed))


@app.get("/memory/timeline")
async def memory_timeline(
    session_id: str = "",
    limit: int = 50,
) -> dict[str, list[dict[str, Any]]]:
    """Return recent memory entries formatted for dashboard timeline rendering."""

    bounded_limit = max(1, min(200, int(limit)))
    fetch_limit = max(bounded_limit, 200 if session_id else bounded_limit)
    orchestrator: Orchestrator = app.state.orchestrator
    rows = await orchestrator.memory_store.list_recent(limit=fetch_limit)
    if session_id:
        rows = [row for row in rows if _memory_matches_session(row, session_id)]
    entries = [_timeline_entry(row) for row in rows[:bounded_limit]]
    return {"entries": entries}


@app.get("/agents/status")
async def agents_status() -> dict[str, Any]:
    """Return idle baseline status for registered swarm/outbound agents."""

    orchestrator: Orchestrator = app.state.orchestrator
    debate = orchestrator.swarm_router.build_debate_swarm()
    growth = orchestrator.growth_router.build_growth_swarm()
    instances = [
        debate.researcher,
        debate.critic,
        debate.devils_advocate,
        debate.fact_checker,
        debate.synthesizer,
        growth.prospector,
        growth.icp,
        growth.outreach,
        growth.nurture,
        growth.revenue_intel,
        growth.partner,
        growth.churn_defense,
        orchestrator.email_agent,
        orchestrator.webchat_agent,
    ]
    deduped: dict[str, dict[str, Any]] = {}
    for agent in instances:
        deduped[agent.name] = {
            "status": "idle",
            "startedAt": None,
            "role": getattr(agent, "role", "fast"),
        }
    return {
        "agents": deduped,
        "edges": [{"source": "orchestrator", "target": name} for name in deduped],
        "updated_at": time.time(),
    }


@app.get("/console/agents")
async def console_agents_tree(request: Request) -> dict[str, Any]:
    """Return ARCHON agents directory tree for the console editor."""

    del request
    root = _console_agents_root()
    if not root.exists():
        return {"root": "archon/agents", "tree": []}
    return {
        "root": "archon/agents",
        "tree": _console_tree_entries(root, root),
    }


@app.get("/console/agents/{path:path}")
async def console_agent_file(path: str, request: Request) -> dict[str, Any]:
    """Load one agent source file by relative path."""

    del request
    target = _console_resolve_agent_path(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Agent file not found.")
    if target.suffix != ".py":
        raise HTTPException(status_code=404, detail="Only Python files are editable.")
    rel = target.relative_to(_console_agents_root()).as_posix()
    content = target.read_text(encoding="utf-8")
    return {
        "path": rel,
        "content": content,
        "read_only": _console_is_read_only(rel),
    }


@app.put("/console/agents/{path:path}")
async def console_save_agent_file(
    path: str,
    payload: ConsoleAgentUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    """Persist one agent source file after Python syntax validation."""

    del request
    target = _console_resolve_agent_path(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Agent file not found.")
    rel = target.relative_to(_console_agents_root()).as_posix()
    if _console_is_read_only(rel):
        raise HTTPException(status_code=403, detail="This file is read-only in console mode.")
    try:
        ast.parse(payload.content, filename=rel)
    except SyntaxError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "syntax_error",
                "message": exc.msg,
                "line": exc.lineno,
                "offset": exc.offset,
            },
        ) from exc
    target.write_text(payload.content, encoding="utf-8")
    return {
        "status": "saved",
        "path": rel,
        "bytes": len(payload.content.encode("utf-8")),
    }


@app.get("/console/providers/validate")
async def console_providers_validate(request: Request) -> dict[str, Any]:
    """Return tenant-scoped provider readiness badges for console BYOK UI."""

    tenant_id = request.state.auth.tenant_id
    rows = [_provider_status_row(app, tenant_id, name) for name in sorted(PROVIDER_ENV_KEY)]
    return {"providers": rows}


@app.post("/console/providers/test/{name}")
async def console_provider_test(name: str, request: Request) -> dict[str, Any]:
    """Run one lightweight provider health check for console UI."""

    normalized = str(name).strip().lower()
    if normalized not in PROVIDER_ENV_KEY:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{normalized}'.")
    tenant_id = request.state.auth.tenant_id
    row = _provider_status_row(app, tenant_id, normalized)
    return {
        "provider": normalized,
        "ok": row["status"] == "healthy",
        "status": row["status"],
        "detail": row["detail"],
        "base_url": row["base_url"],
        "checked_at": time.time(),
    }


@app.post("/console/config")
async def console_save_config(
    payload: ConsoleConfigRequest,
    request: Request,
) -> dict[str, Any]:
    """Persist tenant-scoped BYOK secrets + budget constraints for console flows."""

    tenant_id = request.state.auth.tenant_id
    bucket = _console_tenant_bucket(app, tenant_id)
    providers = bucket.setdefault("providers", {})
    budget = bucket.setdefault("budget", {})

    for raw_name, provider_payload in payload.providers.items():
        normalized = str(raw_name).strip().lower()
        if normalized not in PROVIDER_ENV_KEY:
            raise HTTPException(status_code=404, detail=f"Unknown provider '{normalized}'.")
        key = provider_payload.api_key
        key = key.strip() if isinstance(key, str) else None
        if key:
            providers[normalized] = {"api_key": key, "updated_at": time.time()}
        else:
            providers.pop(normalized, None)

    if payload.budget.daily_limit_usd is not None:
        budget["daily_limit_usd"] = float(payload.budget.daily_limit_usd)
    if payload.budget.monthly_limit_usd is not None:
        budget["monthly_limit_usd"] = float(payload.budget.monthly_limit_usd)
        app.state.orchestrator.config.byok.budget_per_month_usd = float(
            payload.budget.monthly_limit_usd
        )
    if payload.budget.per_request_limit_usd is not None:
        budget["per_request_limit_usd"] = float(payload.budget.per_request_limit_usd)
        app.state.orchestrator.config.byok.budget_per_task_usd = float(
            payload.budget.per_request_limit_usd
        )

    bucket["updated_at"] = time.time()
    provider_rows = [
        _provider_status_row(app, tenant_id, name) for name in sorted(PROVIDER_ENV_KEY)
    ]
    return {
        "status": "saved",
        "providers": provider_rows,
        "budget": budget,
        "updated_at": bucket["updated_at"],
    }


@app.post("/console/crawl")
async def console_crawl(
    payload: ConsoleCrawlRequest,
    request: Request,
) -> dict[str, Any]:
    """Crawl a site, infer intent, and generate ARCHON embed snippet."""

    url = str(payload.url).strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=422, detail="url must start with http:// or https://")

    crawler = SiteCrawler(max_concurrent=3, delay_between_requests_ms=0)
    try:
        crawl_result = await crawler.crawl(url, max_pages=6, max_depth=1)
    finally:
        await crawler.aclose()

    if not crawl_result.pages:
        raise HTTPException(status_code=422, detail="No crawlable pages found for URL.")

    classifier = IntentClassifier()
    site_intent = await classifier.classify_site(crawl_result)

    tenant_id = request.state.auth.tenant_id
    api_key = str(payload.api_key or "").strip() or _tenant_provider_key(
        app, tenant_id, "openrouter"
    )
    if not api_key:
        api_key = f"tenant-{tenant_id}"

    script_src = f"{str(request.base_url).rstrip('/')}/webchat/static/archon-chat.js"
    generator = InjectionGenerator(script_src=script_src)
    embed = generator.generate(api_key=api_key, site_intent=site_intent, options=payload.options)
    return {
        "url": url,
        "site_intent": _site_intent_to_payload(site_intent),
        "embed": {
            "script_tag": embed.script_tag,
            "snippet": generator.generate_full_snippet(embed),
            "suggested_mode": embed.suggested_mode,
            "suggested_greeting": embed.suggested_greeting,
        },
    }


@app.post("/v1/tasks", response_model=TaskResponse)
@limiter.limit(limit_for_key)
async def run_task(request: Request, payload: TaskRequest) -> TaskResponse:
    """Run one orchestration task and return final synthesis."""

    orchestrator: Orchestrator = app.state.orchestrator
    context = dict(payload.context)
    context.setdefault("tenant_id", request.state.auth.tenant_id)
    try:
        result = await orchestrator.execute(
            goal=payload.goal,
            mode=payload.mode,
            language=payload.language,
            context=context,
        )
        await _meter_task_billing_usage(
            tenant_id=request.state.auth.tenant_id,
            task_id=result.task_id,
            budget=result.budget,
        )
        await _emit_task_analytics(
            tenant_id=request.state.auth.tenant_id,
            result=result,
        )
    except Exception as exc:  # pragma: no cover - generic scaffold guard
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _to_response(result)


@app.websocket("/v1/tasks/ws")
async def run_task_ws(websocket: WebSocket) -> None:
    """Run one orchestration task and stream task events over WebSocket."""

    try:
        auth_settings: AuthSettings = app.state.auth_settings
        websocket.state.auth = websocket_auth_context(websocket, auth_settings)
    except HTTPException:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    orchestrator: Orchestrator = app.state.orchestrator

    try:
        incoming = await websocket.receive_json()
        request = TaskRequest.model_validate(incoming)
        context = dict(request.context)
        context.setdefault("tenant_id", websocket.state.auth.tenant_id)

        async def sink(event: dict[str, Any]) -> None:
            if str(event.get("type", "")) == "approval_required":
                await _emit_analytics_event(
                    {
                        "tenant_id": websocket.state.auth.tenant_id,
                        "event_type": "approval_requested",
                        "request_id": str(event.get("request_id") or event.get("action_id") or ""),
                        "action": str(event.get("action") or event.get("action_type") or ""),
                    }
                )
            await websocket.send_json({"type": "event", "payload": event})

        result = await orchestrator.execute(
            goal=request.goal,
            mode=request.mode,
            language=request.language,
            context=context,
            event_sink=sink,
        )
        await _meter_task_billing_usage(
            tenant_id=websocket.state.auth.tenant_id,
            task_id=result.task_id,
            budget=result.budget,
        )
        await _emit_task_analytics(
            tenant_id=websocket.state.auth.tenant_id,
            result=result,
        )
        await websocket.send_json({"type": "result", "payload": _to_response(result).model_dump()})
    except WebSocketDisconnect:
        return
    except Exception as exc:  # pragma: no cover - generic scaffold guard
        await websocket.send_json({"type": "error", "payload": {"message": str(exc)}})


@app.post("/v1/approvals/{request_id}/approve")
@limiter.limit(limit_for_key)
async def approve_guarded_action(
    request: Request,
    request_id: str,
    payload: ApprovalActionRequest,
) -> dict[str, Any]:
    """Approve a pending approval-gate request."""

    approver = payload.approver or request.state.auth.tenant_id
    orchestrator: Orchestrator = app.state.orchestrator
    ok = orchestrator.approval_gate.approve(request_id, approver=approver, notes=payload.notes)
    if not ok:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    await _emit_analytics_event(
        {
            "tenant_id": request.state.auth.tenant_id,
            "event_type": "approval_granted",
            "request_id": request_id,
            "approver": approver,
        }
    )
    sync_store = getattr(app.state, "mobile_sync_store", None)
    if isinstance(sync_store, MobileSyncStore):
        sync_store.record_event(
            tenant_id=request.state.auth.tenant_id,
            event_type="approval_resolved",
            payload={"request_id": request_id, "action": "approve", "channel": "api"},
        )
    push_notifier = getattr(app.state, "mobile_push_notifier", None)
    if isinstance(push_notifier, PushNotifier):
        push_notifier.send_background_refresh(
            request.state.auth.tenant_id,
            reason="approval_resolved",
            request_id=request_id,
        )
    return {"status": "approved", "request_id": request_id}


@app.post("/v1/approvals/{request_id}/deny")
@limiter.limit(limit_for_key)
async def deny_guarded_action(
    request: Request,
    request_id: str,
    payload: ApprovalActionRequest,
) -> dict[str, Any]:
    """Deny a pending approval-gate request."""

    approver = payload.approver or request.state.auth.tenant_id
    orchestrator: Orchestrator = app.state.orchestrator
    ok = orchestrator.approval_gate.deny(request_id, approver=approver, notes=payload.notes)
    if not ok:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    await _emit_analytics_event(
        {
            "tenant_id": request.state.auth.tenant_id,
            "event_type": "approval_denied",
            "request_id": request_id,
            "approver": approver,
        }
    )
    sync_store = getattr(app.state, "mobile_sync_store", None)
    if isinstance(sync_store, MobileSyncStore):
        sync_store.record_event(
            tenant_id=request.state.auth.tenant_id,
            event_type="approval_resolved",
            payload={"request_id": request_id, "action": "deny", "channel": "api"},
        )
    push_notifier = getattr(app.state, "mobile_push_notifier", None)
    if isinstance(push_notifier, PushNotifier):
        push_notifier.send_background_refresh(
            request.state.auth.tenant_id,
            reason="approval_resolved",
            request_id=request_id,
        )
    return {"status": "denied", "request_id": request_id}


@app.post("/v1/outbound/email", response_model=EmailOutboundResponse)
@limiter.limit(limit_for_key)
async def send_outbound_email(
    request: Request,
    payload: EmailOutboundRequest,
) -> EmailOutboundResponse:
    """Send one outbound email using approval-gated execution."""

    orchestrator: Orchestrator = app.state.orchestrator

    sink = None
    if payload.auto_approve:
        approver = request.state.auth.tenant_id

        async def sink(event: dict[str, Any]) -> None:
            if event.get("type") == "approval_required":
                orchestrator.approval_gate.approve(
                    str(event["request_id"]),
                    approver=approver,
                    notes="Auto-approved by authenticated operator via REST.",
                )

    try:
        result = await orchestrator.email_agent.send_email(
            task_id=f"email-{request.state.auth.tenant_id}",
            to_email=payload.to_email,
            subject=payload.subject,
            body=payload.body,
            from_email=payload.from_email,
            reply_to=payload.reply_to,
            metadata=payload.metadata,
            event_sink=sink,
        )
    except ApprovalRequiredError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"{exc} Use websocket approval flow or set auto_approve=true.",
        ) from exc
    except ApprovalDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - external transport failure
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    provider_name = str(result.metadata.get("provider", "")).strip()
    await _meter_outbound_action(
        tenant_id=request.state.auth.tenant_id,
        action_type="outbound_email",
        provider=provider_name,
        task_id=f"email-{request.state.auth.tenant_id}",
    )
    await _emit_analytics_event(
        {
            "tenant_id": request.state.auth.tenant_id,
            "event_type": "email_sent",
            "provider": provider_name,
            "task_id": f"email-{request.state.auth.tenant_id}",
        }
    )

    return EmailOutboundResponse(
        status="sent",
        result={
            "agent": result.agent,
            "output": result.output,
            "confidence": result.confidence,
            "metadata": result.metadata,
        },
    )


@app.post("/v1/outbound/webchat", response_model=WebChatOutboundResponse)
@limiter.limit(limit_for_key)
async def send_outbound_webchat(
    request: Request,
    payload: WebChatOutboundRequest,
) -> WebChatOutboundResponse:
    """Send one outbound webchat message using approval-gated execution."""

    orchestrator: Orchestrator = app.state.orchestrator

    sink = None
    if payload.auto_approve:
        approver = request.state.auth.tenant_id

        async def sink(event: dict[str, Any]) -> None:
            if event.get("type") == "approval_required":
                orchestrator.approval_gate.approve(
                    str(event["request_id"]),
                    approver=approver,
                    notes="Auto-approved by authenticated operator via REST.",
                )

    try:
        result = await orchestrator.webchat_agent.send_message(
            task_id=f"webchat-{request.state.auth.tenant_id}",
            session_id=payload.session_id,
            text=payload.text,
            metadata=payload.metadata,
            event_sink=sink,
        )
    except ApprovalRequiredError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"{exc} Use websocket approval flow or set auto_approve=true.",
        ) from exc
    except ApprovalDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - external transport failure
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    provider_name = str(result.metadata.get("provider", "")).strip()
    await _meter_outbound_action(
        tenant_id=request.state.auth.tenant_id,
        action_type="outbound_webchat",
        provider=provider_name,
        task_id=f"webchat-{request.state.auth.tenant_id}",
    )
    await _emit_analytics_event(
        {
            "tenant_id": request.state.auth.tenant_id,
            "event_type": "message_sent",
            "provider": provider_name,
            "task_id": f"webchat-{request.state.auth.tenant_id}",
            "session_id": payload.session_id,
        }
    )

    return WebChatOutboundResponse(
        status="sent",
        result={
            "agent": result.agent,
            "output": result.output,
            "confidence": result.confidence,
            "metadata": result.metadata,
        },
    )


@app.post("/studio/workflows")
async def studio_save_workflow(
    payload: StudioWorkflowRequest,
    request: Request,
) -> dict[str, Any]:
    """Persist one Studio workflow definition for the authenticated tenant."""

    tenant_id = request.state.auth.tenant_id
    workflow = _studio_request_to_workflow(payload)
    store = _studio_store()
    saved = store.save(tenant_id, workflow, workflow_id=payload.workflow_id)
    await _emit_analytics_event(
        {
            "tenant_id": tenant_id,
            "event_type": "workflow_created",
            "workflow_id": saved.workflow_id,
            "name": saved.name,
        }
    )
    return {
        "workflow_id": saved.workflow_id,
        "name": saved.name,
        "updated_at": saved.updated_at,
    }


@app.get("/studio/workflows")
async def studio_list_workflows(request: Request) -> list[dict[str, Any]]:
    """List Studio workflows for the authenticated tenant."""

    tenant_id = request.state.auth.tenant_id
    store = _studio_store()
    return [
        {
            "id": row.workflow_id,
            "name": row.name,
            "updated_at": row.updated_at,
        }
        for row in store.list(tenant_id)
    ]


@app.get("/studio/workflows/{workflow_id}")
async def studio_get_workflow(workflow_id: str, request: Request) -> dict[str, Any]:
    """Load one Studio workflow definition."""

    tenant_id = request.state.auth.tenant_id
    workflow = _studio_store().get(tenant_id, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return _workflow_to_payload(workflow)


@app.delete("/studio/workflows/{workflow_id}")
async def studio_delete_workflow(workflow_id: str, request: Request) -> dict[str, Any]:
    """Delete one Studio workflow definition."""

    tenant_id = request.state.auth.tenant_id
    deleted = _studio_store().delete(tenant_id, workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    await _emit_analytics_event(
        {
            "tenant_id": tenant_id,
            "event_type": "state_change",
            "workflow_id": workflow_id,
            "state": "studio_workflow_deleted",
        }
    )
    return {"status": "deleted", "workflow_id": workflow_id}


@app.post("/studio/run")
async def studio_run_workflow(
    payload: StudioRunRequest,
    request: Request,
) -> dict[str, Any]:
    """Validate and execute one Studio workflow definition."""

    tenant_id = request.state.auth.tenant_id
    errors = validate_studio_workflow(payload.workflow)
    if errors:
        raise HTTPException(
            status_code=422,
            detail=[
                {"code": error.code, "message": error.message, "node_id": error.node_id}
                for error in errors
            ],
        )
    workflow = _workflow_from_payload(payload.workflow)
    broker: WorkflowRunBroker = app.state.studio_run_broker
    run = broker.create_run(tenant_id, workflow.workflow_id)
    asyncio.create_task(
        execute_workflow_run(
            broker=broker,
            run_id=run.run_id,
            workflow=workflow,
            orchestrator=app.state.orchestrator,
            tenant_id=tenant_id,
        )
    )
    await _emit_analytics_event(
        {
            "tenant_id": tenant_id,
            "event_type": "state_change",
            "workflow_id": workflow.workflow_id,
            "run_id": run.run_id,
            "state": "studio_workflow_run_started",
        }
    )
    return {
        "run_id": run.run_id,
        "workflow_id": workflow.workflow_id,
        "websocket_path": f"/studio/run/ws/{run.run_id}",
    }


@app.websocket("/studio/run/ws/{run_id}")
async def studio_run_ws(websocket: WebSocket, run_id: str) -> None:
    """Stream Studio workflow execution events over WebSocket."""

    try:
        auth_settings: AuthSettings = app.state.auth_settings
        websocket.state.auth = websocket_auth_context(websocket, auth_settings)
    except HTTPException:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    broker: WorkflowRunBroker = app.state.studio_run_broker
    try:
        async for event in broker.subscribe(run_id):
            await websocket.send_json(event)
    except KeyError:
        await websocket.send_json({"type": "error", "message": "Unknown run_id."})
    except WebSocketDisconnect:
        return


@app.post("/federation/tasks/bid")
async def federation_bid(payload: FederationTaskRequest, request: Request) -> dict[str, Any]:
    """Return local bid for an incoming federated task."""

    del request
    required = [str(item).strip().lower() for item in payload.required_capabilities if str(item)]
    local_capabilities = {"debate", "growth", "analysis", "reasoning", "translation"}
    missing = [item for item in required if item not in local_capabilities]
    can_fulfill = not missing

    estimated_cost = round(0.02 * max(1, len(required)), 6)
    estimated_time = round(2.0 + (0.75 * max(1, len(required))), 3)
    confidence = 0.9 if can_fulfill else 0.15
    bid = {
        "peer_id": str(os.getenv("ARCHON_INSTANCE_ID", "local-instance")),
        "can_fulfill": can_fulfill,
        "estimated_cost_usd": estimated_cost,
        "estimated_time_s": estimated_time,
        "confidence": confidence,
    }
    await _emit_analytics_event(
        {
            "event_type": "federation_bid_requested",
            "task_id": payload.task_id,
            "requester_instance_id": payload.requester_instance_id,
            "can_fulfill": can_fulfill,
            "missing_capabilities": missing,
        }
    )
    return bid


@app.post("/federation/tasks/execute")
async def federation_execute(
    payload: FederationTaskRequest,
    request: Request,
) -> StreamingResponse:
    """Execute federated task locally and stream result tokens back to requester."""

    orchestrator: Orchestrator = app.state.orchestrator
    auth = getattr(request.state, "auth", None)
    tenant_id = getattr(auth, "tenant_id", "system")

    async def _event_stream():
        started = time.monotonic()
        success = True
        result_text = ""
        spent_usd = 0.0
        try:
            result = await orchestrator.execute(
                goal=payload.description,
                mode="debate",
                context={
                    "tenant_id": tenant_id,
                    "federation_task_id": payload.task_id,
                    "requester_instance_id": payload.requester_instance_id,
                    "federation_context": payload.context,
                },
            )
            result_text = str(result.final_answer or "")
            spent_usd = float(result.budget.get("spent_usd", 0.0) or 0.0)
            await _meter_task_billing_usage(
                tenant_id=tenant_id,
                task_id=result.task_id,
                budget=result.budget,
            )
            usage_meter = getattr(app.state, "usage_meter", None)
            if isinstance(usage_meter, UsageMeter):
                usage_meter.record(
                    tenant_id=tenant_id,
                    metric="federation_tasks",
                    quantity=1.0,
                    metadata={"task_id": payload.task_id},
                )
            await _emit_task_analytics(
                tenant_id=tenant_id,
                result=result,
                federated=True,
            )
            for token in _tokenize_federation(result_text):
                yield json.dumps({"type": "token", "content": token}) + "\n"
            yield (
                json.dumps(
                    {
                        "type": "result",
                        "task_id": payload.task_id,
                        "result": result_text,
                        "cost_usd": spent_usd,
                        "time_s": round(max(0.0, time.monotonic() - started), 6),
                        "success": True,
                    }
                )
                + "\n"
            )
        except Exception as exc:
            success = False
            yield (
                json.dumps(
                    {
                        "type": "result",
                        "task_id": payload.task_id,
                        "result": "",
                        "cost_usd": spent_usd,
                        "time_s": round(max(0.0, time.monotonic() - started), 6),
                        "success": False,
                        "error": str(exc),
                    }
                )
                + "\n"
            )
        finally:
            await _emit_analytics_event(
                {
                    "tenant_id": tenant_id,
                    "event_type": "federation_task_executed",
                    "task_id": payload.task_id,
                    "requester_instance_id": payload.requester_instance_id,
                    "success": success,
                    "cost_usd": spent_usd,
                    "result_chars": len(result_text),
                }
            )

    return StreamingResponse(_event_stream(), media_type="application/x-ndjson")


@app.post("/marketplace/developers/onboard")
@limiter.limit(limit_for_key)
async def marketplace_developer_onboard(
    payload: MarketplaceOnboardRequest,
    request: Request,
) -> dict[str, Any]:
    """Create a Stripe Connect onboarding link for one partner."""

    _require_enterprise(request, status_code=401)
    onboarding = _marketplace_onboarding()
    try:
        session = await onboarding.onboard(payload.partner_id, payload.email, payload.country)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await _emit_analytics_event(
        {
            "tenant_id": request.state.auth.tenant_id,
            "event_type": "state_change",
            "partner_id": payload.partner_id,
            "session_id": session.session_id,
            "state": "marketplace_onboarding_created",
        }
    )
    return {
        "onboarding_url": session.onboarding_url,
        "session_id": session.session_id,
        "expires_at": session.expires_at,
    }


@app.get("/marketplace/developers/{partner_id}/status")
@limiter.limit(limit_for_key)
async def marketplace_developer_status(partner_id: str, request: Request) -> dict[str, Any]:
    """Return the stored Stripe Connect account projection for one partner."""

    _require_enterprise(request, status_code=401)
    onboarding = _marketplace_onboarding()
    try:
        account, complete = await onboarding.status(partner_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = asdict(account)
    payload["onboarding_complete"] = complete
    return payload


@app.post("/marketplace/developers/{partner_id}/refresh")
@limiter.limit(limit_for_key)
async def marketplace_developer_refresh(partner_id: str, request: Request) -> dict[str, Any]:
    """Refresh one partner's onboarding link when needed."""

    _require_enterprise(request, status_code=401)
    onboarding = _marketplace_onboarding()
    try:
        session = await onboarding.refresh(partner_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await _emit_analytics_event(
        {
            "tenant_id": request.state.auth.tenant_id,
            "event_type": "state_change",
            "partner_id": partner_id,
            "session_id": session.session_id,
            "state": "marketplace_onboarding_refreshed",
        }
    )
    return {
        "onboarding_url": session.onboarding_url,
        "session_id": session.session_id,
        "expires_at": session.expires_at,
    }


@app.get("/marketplace/developers/{partner_id}/earnings")
@limiter.limit(limit_for_key)
async def marketplace_developer_earnings(
    partner_id: str,
    request: Request,
    period_start: float | None = None,
    period_end: float | None = None,
) -> dict[str, Any]:
    """Return one developer's earnings plus payout history."""

    _require_partner_or_enterprise(request, partner_id)
    start, end = _resolve_marketplace_period(period_start=period_start, period_end=period_end)
    earnings = _marketplace_revenue_ledger().aggregate_developer(partner_id, start, end)
    payouts = _marketplace_payout_queue().list_payouts(
        partner_id=partner_id,
        period_start=start,
        period_end=end,
    )
    payload = asdict(earnings)
    payload["payout_history"] = [asdict(row) for row in payouts]
    return payload


@app.get("/marketplace/developers/{partner_id}/payouts")
@limiter.limit(limit_for_key)
async def marketplace_developer_payouts(partner_id: str, request: Request) -> list[dict[str, Any]]:
    """Return payout history for one partner."""

    _require_partner_or_enterprise(request, partner_id)
    return [asdict(row) for row in _marketplace_payout_queue().list_payouts(partner_id=partner_id)]


@app.get("/marketplace/revenue/summary")
@limiter.limit(limit_for_key)
async def marketplace_revenue_summary(
    request: Request,
    period_start: float | None = None,
    period_end: float | None = None,
) -> dict[str, Any]:
    """Return ARCHON marketplace revenue totals for the selected period."""

    _require_enterprise(request, status_code=403)
    start, end = _resolve_marketplace_period(period_start=period_start, period_end=period_end)
    return asdict(_marketplace_revenue_ledger().aggregate_archon(start, end))


@app.post("/marketplace/revenue/run-cycle")
@limiter.limit(limit_for_key)
async def marketplace_revenue_run_cycle(
    payload: MarketplaceRunCycleRequest,
    request: Request,
) -> dict[str, Any]:
    """Run one marketplace payout cycle for the requested monthly period."""

    _require_enterprise(request, status_code=403)
    start, end = _resolve_marketplace_period(
        period_start=payload.period_start,
        period_end=payload.period_end,
        period=payload.period,
    )
    orchestrator = _marketplace_payout_orchestrator()
    sink = None
    if payload.auto_approve:
        approval_gate = getattr(app.state.orchestrator, "approval_gate", None)

        async def sink(event: dict[str, Any]) -> None:
            if event.get("type") == "approval_required" and approval_gate is not None:
                approval_gate.approve(
                    str(event.get("request_id", "")),
                    approver=request.state.auth.tenant_id,
                    notes="Auto-approved by authenticated marketplace operator.",
                )

    try:
        result = await orchestrator.run_cycle(start, end, event_sink=sink)
    except ApprovalRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ApprovalDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await _emit_analytics_event(
        {
            "tenant_id": request.state.auth.tenant_id,
            "event_type": "state_change",
            "cycle_id": result.cycle_id,
            "state": "marketplace_payout_cycle_executed",
            "partners_paid": result.partners_paid,
            "total_paid_usd": result.total_paid_usd,
        }
    )
    return asdict(result)


def _marketplace_onboarding() -> DeveloperOnboarding:
    onboarding = getattr(app.state, "marketplace_onboarding", None)
    if not isinstance(onboarding, DeveloperOnboarding):
        raise HTTPException(status_code=503, detail="Marketplace onboarding is unavailable.")
    return onboarding


def _marketplace_revenue_ledger() -> RevenueShareLedger:
    ledger = getattr(app.state, "marketplace_revenue_ledger", None)
    if not isinstance(ledger, RevenueShareLedger):
        raise HTTPException(status_code=503, detail="Marketplace revenue ledger is unavailable.")
    return ledger


def _marketplace_payout_queue() -> PayoutQueue:
    queue = getattr(app.state, "marketplace_payout_queue", None)
    if not isinstance(queue, PayoutQueue):
        raise HTTPException(status_code=503, detail="Marketplace payout queue is unavailable.")
    return queue


def _marketplace_payout_orchestrator() -> PayoutOrchestrator:
    orchestrator = getattr(app.state, "marketplace_payout_orchestrator", None)
    if not isinstance(orchestrator, PayoutOrchestrator):
        raise HTTPException(
            status_code=503,
            detail="Marketplace payout orchestrator is unavailable.",
        )
    return orchestrator


def _marketplace_revenue_report() -> PartnerRevenueReport:
    reporter = getattr(app.state, "marketplace_revenue_report", None)
    if not isinstance(reporter, PartnerRevenueReport):
        raise HTTPException(status_code=503, detail="Marketplace report generator is unavailable.")
    return reporter


def _require_enterprise(request: Request, *, status_code: int) -> None:
    auth = getattr(request.state, "auth", None)
    if getattr(auth, "tier", "") != "enterprise":
        raise HTTPException(status_code=status_code, detail="Enterprise tier required.")


def _require_partner_or_enterprise(request: Request, partner_id: str) -> None:
    auth = getattr(request.state, "auth", None)
    if getattr(auth, "tier", "") == "enterprise":
        return
    if str(getattr(auth, "tenant_id", "")).strip() == str(partner_id or "").strip():
        return
    raise HTTPException(status_code=401, detail="Partner scope mismatch.")


def _resolve_marketplace_period(
    *,
    period_start: float | None = None,
    period_end: float | None = None,
    period: str | None = None,
) -> tuple[float, float]:
    if period:
        return _marketplace_month_bounds(period)
    if period_start is not None and period_end is not None:
        start = float(period_start)
        end = float(period_end)
        if end < start:
            raise HTTPException(status_code=422, detail="period_end must be >= period_start.")
        return start, end
    return _current_month_bounds()


def _marketplace_month_bounds(period: str) -> tuple[float, float]:
    text = str(period or "").strip()
    try:
        year, month = text.split("-", 1)
        year_num = int(year)
        month_num = int(month)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="period must be YYYY-MM.") from exc
    if month_num < 1 or month_num > 12:
        raise HTTPException(status_code=422, detail="period must be YYYY-MM.")
    start = datetime(year_num, month_num, 1, tzinfo=timezone.utc)
    if month_num == 12:
        end = datetime(year_num + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year_num, month_num + 1, 1, tzinfo=timezone.utc)
    return start.timestamp(), end.timestamp()


def _current_month_bounds() -> tuple[float, float]:
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return start.timestamp(), end.timestamp()


def run() -> None:
    """Console script entrypoint used by `archon-server`."""

    host = os.getenv("ARCHON_HOST", "127.0.0.1")
    port = int(os.getenv("ARCHON_PORT", "8000"))
    if not _has_websocket_transport():
        raise RuntimeError(
            "ARCHON server requires websocket support. Install 'websockets' "
            "(preferred) or 'wsproto', then restart the server."
        )
    lock_path = _acquire_managed_server_slot(host=host, port=port)
    try:
        uvicorn.run("archon.interfaces.api.server:app", host=host, port=port, reload=False)
    finally:
        _clear_managed_server_slot(lock_path, pid=os.getpid())


def _memory_matches_session(row: dict[str, Any], session_id: str) -> bool:
    context = row.get("context")
    if not isinstance(context, dict):
        return False
    if str(context.get("session_id", "")).strip() == session_id:
        return True
    nested = context.get("input_context")
    if isinstance(nested, dict) and str(nested.get("session_id", "")).strip() == session_id:
        return True
    return False


def _has_websocket_transport() -> bool:
    return (
        importlib.util.find_spec("websockets") is not None
        or importlib.util.find_spec("wsproto") is not None
    )


def _acquire_managed_server_slot(*, host: str, port: int) -> Path:
    lock_path = _managed_server_lock_path(host, port)
    payload = _read_managed_server_lock(lock_path)
    managed_pid = int(payload.get("pid") or 0) if isinstance(payload, dict) else 0
    current_pid = os.getpid()
    if managed_pid > 0 and managed_pid != current_pid and _process_is_running(managed_pid):
        _terminate_process(managed_pid)
        _wait_for_process_exit(managed_pid, timeout_s=5.0)
    _clear_managed_server_slot(lock_path)
    if not _port_is_bindable(host, port):
        raise RuntimeError(
            f"ARCHON could not start on {host}:{port} because the port is already in use "
            "by an unmanaged process. Stop it or choose a different port."
        )
    _write_managed_server_lock(lock_path, pid=current_pid, host=host, port=port)
    return lock_path


def _managed_server_lock_path(host: str, port: int) -> Path:
    runtime_dir = _archon_runtime_dir() / "runtime"
    safe_host = str(host or "127.0.0.1").replace(":", "_").replace("/", "_").replace("\\", "_")
    return runtime_dir / f"server-{safe_host}-{int(port)}.json"


def _archon_runtime_dir() -> Path:
    configured = str(os.getenv("ARCHON_RUNTIME_DIR", "")).strip()
    if configured:
        root = Path(configured)
    elif os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA", tempfile.gettempdir())) / "ARCHON"
    else:
        root = Path.home() / ".archon"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _read_managed_server_lock(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_managed_server_lock(path: Path, *, pid: int, host: str, port: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pid": int(pid),
                "host": str(host),
                "port": int(port),
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )


def _clear_managed_server_slot(path: Path, *, pid: int | None = None) -> None:
    if pid is not None:
        payload = _read_managed_server_lock(path)
        locked_pid = int(payload.get("pid") or 0) if isinstance(payload, dict) else 0
        if locked_pid not in {0, int(pid)}:
            return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        output = str(result.stdout or "").strip()
        if not output or output.lower().startswith("info: no tasks"):
            return False
        return f'"{pid}"' in output or f",{pid}," in output
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminate_process(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        combined = f"{result.stdout}\n{result.stderr}".lower()
        if (
            result.returncode != 0
            and "not found" not in combined
            and "no running instance" not in combined
        ):
            raise RuntimeError(f"ARCHON could not stop the previous server process {pid}.")
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError as exc:
        raise RuntimeError(f"ARCHON could not stop the previous server process {pid}.") from exc
    if _wait_for_process_exit(pid, timeout_s=2.0):
        return
    os.kill(pid, signal.SIGKILL)


def _wait_for_process_exit(pid: int, *, timeout_s: float) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while time.monotonic() < deadline:
        if not _process_is_running(pid):
            return True
        time.sleep(0.1)
    return not _process_is_running(pid)


def _port_is_bindable(host: str, port: int) -> bool:
    bind_host = host or "127.0.0.1"
    try:
        infos = socket.getaddrinfo(bind_host, int(port), type=socket.SOCK_STREAM)
    except socket.gaierror:
        infos = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (bind_host, int(port)))]
    for family, socktype, proto, _canonname, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(sockaddr)
            return True
        except OSError:
            continue
        finally:
            sock.close()
    return False


def _timeline_entry(row: dict[str, Any]) -> dict[str, Any]:
    memory_id = str(row.get("id", ""))
    created_at = str(row.get("created_at", "")).strip()
    actual_outcome = str(row.get("actual_outcome", "")).strip()
    task = str(row.get("task", "")).strip()
    causal_reasoning = str(row.get("causal_reasoning", "")).strip()
    return {
        "memory_id": memory_id,
        "timestamp": _to_unix_timestamp(created_at),
        "role": "assistant",
        "content": actual_outcome or task,
        "causal_links": [
            {
                "chain_id": f"chain-{memory_id}",
                "effect": (actual_outcome or task)[:80],
            }
        ],
        "causal_chain": [
            {
                "chain_id": f"chain-{memory_id}",
                "cause": causal_reasoning,
                "effect": actual_outcome or task,
                "confidence": 1.0,
            }
        ],
        "metadata": {
            "task": task,
            "delta": row.get("delta"),
            "reuse_conditions": row.get("reuse_conditions"),
        },
    }


def _to_unix_timestamp(raw: str) -> float:
    text = str(raw).strip()
    if not text:
        return time.time()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return time.time()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _console_agents_root() -> Path:
    return Path(__file__).resolve().parents[2] / "agents"


def _console_tenant_bucket(app: FastAPI, tenant_id: str) -> dict[str, Any]:
    store = getattr(app.state, "console_tenant_config", None)
    if not isinstance(store, dict):
        store = {}
        app.state.console_tenant_config = store
    bucket = store.setdefault(tenant_id, {})
    if not isinstance(bucket, dict):
        bucket = {}
        store[tenant_id] = bucket
    bucket.setdefault("providers", {})
    bucket.setdefault("budget", {})
    return bucket


def _tenant_provider_key(app: FastAPI, tenant_id: str, provider_name: str) -> str:
    bucket = _console_tenant_bucket(app, tenant_id)
    providers = bucket.get("providers")
    if isinstance(providers, dict):
        candidate = providers.get(provider_name, {})
        if isinstance(candidate, dict):
            value = str(candidate.get("api_key", "")).strip()
            if value:
                return value
    env_name = PROVIDER_ENV_KEY.get(provider_name)
    if env_name:
        env_value = str(os.getenv(env_name, "")).strip()
        if env_value:
            return env_value
    if provider_name == "ollama":
        return "ollama"
    return ""


def _provider_status_row(app: FastAPI, tenant_id: str, provider_name: str) -> dict[str, Any]:
    key = _tenant_provider_key(app, tenant_id, provider_name)
    has_key = bool(key)
    status = "healthy" if has_key else "missing_key"
    source = "tenant_config" if has_key else "none"
    if not has_key:
        env_name = PROVIDER_ENV_KEY.get(provider_name)
        if env_name and str(os.getenv(env_name, "")).strip():
            source = "env"
    return {
        "name": provider_name,
        "status": status,
        "has_key": has_key,
        "source": source,
        "base_url": DEFAULT_BASE_URL.get(provider_name, ""),
        "detail": "Provider key configured." if has_key else "Missing provider key.",
    }


def _console_resolve_agent_path(path: str) -> Path:
    raw = str(path or "").strip().replace("\\", "/")
    if not raw:
        raise HTTPException(status_code=404, detail="Agent file not found.")
    if raw.startswith("../") or "/../" in f"/{raw}/":
        raise HTTPException(status_code=404, detail="Agent file not found.")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise HTTPException(status_code=404, detail="Agent file not found.")
    root = _console_agents_root().resolve()
    target = (root / candidate).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(status_code=404, detail="Agent file not found.")
    return target


def _console_is_read_only(relative_path: str) -> bool:
    normalized = str(relative_path or "").replace("\\", "/").lstrip("./")
    protected_names = {
        "orchestrator.py",
        "debate_engine.py",
        "swarm_router.py",
        "growth_router.py",
    }
    if normalized.startswith("core/"):
        return True
    return any(normalized.endswith(name) for name in protected_names)


def _console_tree_entries(root: Path, current: Path) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for child in sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        rel = child.relative_to(root).as_posix()
        if child.is_dir():
            nodes.append(
                {
                    "name": child.name,
                    "path": rel,
                    "type": "directory",
                    "children": _console_tree_entries(root, child),
                }
            )
        elif child.suffix == ".py":
            nodes.append(
                {
                    "name": child.name,
                    "path": rel,
                    "type": "file",
                    "read_only": _console_is_read_only(rel),
                }
            )
    return nodes


def _site_intent_to_payload(site_intent: SiteIntent) -> dict[str, Any]:
    confidences = [
        float(page_intent.confidence)
        for page_intent in site_intent.page_intents
        if page_intent.category == site_intent.primary
    ]
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return {
        "primary": site_intent.primary,
        "secondary": site_intent.secondary,
        "confidence": round(confidence, 3),
        "page_count": len(site_intent.page_intents),
    }


def _tokenize_federation(text: str) -> list[str]:
    chunks: list[str] = []
    parts = str(text or "").split(" ")
    for index, word in enumerate(parts):
        suffix = " " if index < len(parts) - 1 else ""
        if word or suffix:
            chunks.append(word + suffix)
    return chunks


async def _emit_analytics_event(payload: dict[str, Any]) -> None:
    collector = getattr(app.state, "analytics_collector", None)
    if collector is None:
        return
    record = getattr(collector, "record", None)
    if not callable(record):
        return
    try:
        event_type = (
            str(payload.get("event_type", "state_change")).strip().lower() or "state_change"
        )
        tenant_id = str(payload.get("tenant_id", "system")).strip() or "system"
        maybe = record(
            tenant_id=tenant_id,
            event_type=event_type,
            properties={
                key: value
                for key, value in dict(payload).items()
                if key not in {"tenant_id", "event_type"}
            },
        )
        if hasattr(maybe, "__await__"):
            await maybe
    except Exception:
        return


async def _meter_task_billing_usage(
    *,
    tenant_id: str,
    task_id: str,
    budget: dict[str, Any],
) -> None:
    service = getattr(app.state, "billing_service", None)
    if not isinstance(service, BillingService):
        return
    raw = budget.get("cost_by_provider_model", {})
    if not isinstance(raw, dict):
        return
    normalized: dict[str, float] = {}
    for key, value in raw.items():
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            normalized[str(key)] = amount
    if normalized:
        await service.record_provider_model_spend(
            tenant_id=tenant_id,
            task_id=task_id,
            cost_by_provider_model=normalized,
        )
    usage_meter = getattr(app.state, "usage_meter", None)
    if isinstance(usage_meter, UsageMeter):
        usage_meter.record(
            tenant_id=tenant_id,
            metric="agent_runs",
            quantity=1.0,
            metadata={"task_id": task_id, "providers": sorted(normalized)},
        )


async def _meter_outbound_action(
    *,
    tenant_id: str,
    action_type: str,
    provider: str,
    task_id: str,
) -> None:
    service = getattr(app.state, "billing_service", None)
    if not isinstance(service, BillingService):
        return
    await service.record_outbound_action(
        tenant_id=tenant_id,
        action_type=action_type,
        provider=provider,
        task_id=task_id,
    )
    usage_meter = getattr(app.state, "usage_meter", None)
    if isinstance(usage_meter, UsageMeter):
        metric = ""
        if action_type == "outbound_email":
            metric = "emails_sent"
        elif action_type == "outbound_whatsapp":
            metric = "whatsapp_sent"
        if metric:
            usage_meter.record(
                tenant_id=tenant_id,
                metric=metric,
                quantity=1.0,
                metadata={"provider": provider, "task_id": task_id},
            )


async def _emit_task_analytics(
    *,
    tenant_id: str,
    result: OrchestrationResult,
    federated: bool = False,
) -> None:
    budget = result.budget if isinstance(result.budget, dict) else {}
    session_id = str(result.task_id).strip() or f"session-{int(time.time())}"

    await _emit_analytics_event(
        {
            "tenant_id": tenant_id,
            "event_type": "session_started",
            "session_id": session_id,
            "task_id": result.task_id,
            "mode": result.mode,
            "federated": federated,
        }
    )

    for row in _task_agent_rows(result):
        metadata = row.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        await _emit_analytics_event(
            {
                "tenant_id": tenant_id,
                "event_type": "agent_recruited",
                "session_id": session_id,
                "task_id": result.task_id,
                "mode": result.mode,
                "agent": row.get("agent"),
                "role": row.get("role"),
                "confidence": row.get("confidence"),
                "provider": metadata.get("provider"),
                "model": metadata.get("model"),
                "cost_usd": metadata.get("cost_usd", 0.0),
                "federated": federated,
            }
        )

    for provider_model, amount in dict(budget.get("cost_by_provider_model", {}) or {}).items():
        provider, model = _split_provider_model(str(provider_model))
        await _emit_analytics_event(
            {
                "tenant_id": tenant_id,
                "event_type": "cost_incurred",
                "session_id": session_id,
                "task_id": result.task_id,
                "mode": result.mode,
                "provider": provider,
                "model": model,
                "cost_usd": float(amount or 0.0),
                "federated": federated,
            }
        )

    await _emit_analytics_event(
        {
            "tenant_id": tenant_id,
            "event_type": "quality_evaluated",
            "session_id": session_id,
            "task_id": result.task_id,
            "mode": result.mode,
            "quality_score": round(float(result.confidence) / 100.0, 4),
            "confidence": result.confidence,
            "federated": federated,
        }
    )

    for optimization in list(budget.get("optimizations", []) or []):
        if not isinstance(optimization, dict):
            continue
        await _emit_analytics_event(
            {
                "tenant_id": tenant_id,
                "event_type": "cost_optimization_applied",
                "session_id": session_id,
                "task_id": result.task_id,
                "mode": result.mode,
                "federated": federated,
                **optimization,
            }
        )

    completion_event = "debate_completed" if result.mode == "debate" else "state_change"
    completion_payload = {
        "tenant_id": tenant_id,
        "event_type": completion_event,
        "session_id": session_id,
        "task_id": result.task_id,
        "mode": result.mode,
        "confidence": result.confidence,
        "spent_usd": float(budget.get("spent_usd", 0.0) or 0.0),
        "federated": federated,
    }
    if completion_event == "state_change":
        completion_payload["state"] = "growth_completed"
    await _emit_analytics_event(completion_payload)

    await _emit_analytics_event(
        {
            "tenant_id": tenant_id,
            "event_type": "session_ended",
            "session_id": session_id,
            "task_id": result.task_id,
            "mode": result.mode,
            "confidence": result.confidence,
            "spent_usd": float(budget.get("spent_usd", 0.0) or 0.0),
            "federated": federated,
        }
    )


def _task_agent_rows(result: OrchestrationResult) -> list[dict[str, Any]]:
    if isinstance(result.debate, dict):
        rounds = result.debate.get("rounds", [])
        return [row for row in rounds if isinstance(row, dict)]
    if isinstance(result.growth, dict):
        reports = result.growth.get("agent_reports", [])
        return [row for row in reports if isinstance(row, dict)]
    return []


def _split_provider_model(raw: str) -> tuple[str, str]:
    provider, _sep, model = str(raw or "").partition("/")
    return provider or "unknown", model or "unknown"


def _billing_tier_for_tenant(app: FastAPI, tenant_id: str) -> str:
    service = getattr(app.state, "billing_service", None)
    if not isinstance(service, BillingService):
        return "free"
    subscription = service.store.get_subscription(str(tenant_id))
    if subscription is None:
        return "free"
    plan = str(subscription.plan_id or "").strip().lower()
    if plan in {"business", "growth", "pro"}:
        return "pro"
    if plan == "enterprise":
        return "enterprise"
    return "free"


def _observability_path_label(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return str(request.url.path or "/")


def _studio_store() -> StudioWorkflowStore:
    store = getattr(app.state, "studio_store", None)
    if not isinstance(store, StudioWorkflowStore):
        raise HTTPException(status_code=503, detail="Studio store is unavailable.")
    return store


def _workflow_from_payload(payload: dict[str, Any]) -> WorkflowDefinition:
    steps = [
        Step(
            step_id=str(step.get("step_id") or ""),
            agent=str(step.get("agent") or ""),
            action=str(step.get("action") or ""),
            config=dict(step.get("config") or {}),
            dependencies=[str(dep) for dep in step.get("dependencies", [])],
        )
        for step in payload.get("steps", [])
        if isinstance(step, dict)
    ]
    return WorkflowDefinition(
        workflow_id=str(payload.get("workflow_id") or f"workflow-{int(time.time())}"),
        name=str(payload.get("name") or "Studio Workflow"),
        steps=steps,
        metadata=dict(payload.get("metadata") or {}),
        version=int(payload.get("version") or 1),
        created_at=float(payload.get("created_at") or time.time()),
    )


def _studio_request_to_workflow(payload: StudioWorkflowRequest) -> WorkflowDefinition:
    return _workflow_from_payload(payload.model_dump(exclude_none=True))


def _workflow_to_payload(workflow: WorkflowDefinition) -> dict[str, Any]:
    return {
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


app.state.webchat_app = mount_webchat(app, path="/webchat")
