"""FastAPI server entrypoint for ARCHON runtime APIs."""

from __future__ import annotations

import ast
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, cast

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from starlette.responses import Response

from archon.config import load_archon_config
from archon.core.approval_gate import ApprovalDeniedError, ApprovalRequiredError
from archon.core.orchestrator import OrchestrationResult, Orchestrator
from archon.interfaces.api.auth import AuthMiddleware, AuthSettings, websocket_auth_context
from archon.interfaces.api.rate_limit import (
    InMemoryTierRateLimitStore,
    create_limiter,
    limit_for_key,
    set_rate_limit_store,
)
from archon.providers.router import DEFAULT_BASE_URL, PROVIDER_ENV_KEY
from archon.web.injection_generator import InjectionGenerator
from archon.web.intent_classifier import IntentClassifier, SiteIntent
from archon.web.site_crawler import SiteCrawler
from archon.interfaces.webchat.server import mount_webchat


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
    budget: dict[str, float | bool]
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
    app.state.started_monotonic = time.monotonic()
    if not isinstance(getattr(app.state, "console_tenant_config", None), dict):
        app.state.console_tenant_config = {}
    if getattr(app.state, "webchat_app", None) is not None:
        app.state.webchat_app.state.runtime.orchestrator = app.state.orchestrator
    try:
        yield
    finally:
        await app.state.orchestrator.aclose()


app = FastAPI(title="ARCHON API", version="0.1.0", lifespan=lifespan)
_exempt_paths = {
    "/health",
    "/healthz",
    "/memory/timeline",
    "/agents/status",
    "/webchat",
    "/webchat/token",
    "/webchat/upgrade",
    "/openapi.json",
    "/docs",
    "/redoc",
}
app.add_middleware(AuthMiddleware, settings=AuthSettings.from_env(), exempt_paths=_exempt_paths)

limiter = create_limiter()
app.state.limiter = limiter
app.state.rate_limit_store = InMemoryTierRateLimitStore.from_env()
set_rate_limit_store(app.state.rate_limit_store)
app.state.started_monotonic = time.monotonic()
app.state.console_tenant_config = {}
_rate_limit_handler = cast(
    Callable[[Request, Exception], Response],
    _rate_limit_exceeded_handler,
)
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.state.webchat_app = mount_webchat(app, path="/webchat")


@app.get("/health")
async def health() -> dict[str, Any]:
    """Runtime health with version and uptime."""

    started = float(getattr(app.state, "started_monotonic", time.monotonic()))
    return {
        "status": "ok",
        "version": app.version,
        "uptime_s": max(0.0, time.monotonic() - started),
    }


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    """Simple readiness probe endpoint."""

    return {"status": "ok"}


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
        app.state.orchestrator.config.byok.budget_per_month_usd = float(payload.budget.monthly_limit_usd)
    if payload.budget.per_request_limit_usd is not None:
        budget["per_request_limit_usd"] = float(payload.budget.per_request_limit_usd)
        app.state.orchestrator.config.byok.budget_per_task_usd = float(payload.budget.per_request_limit_usd)

    bucket["updated_at"] = time.time()
    provider_rows = [_provider_status_row(app, tenant_id, name) for name in sorted(PROVIDER_ENV_KEY)]
    return {"status": "saved", "providers": provider_rows, "budget": budget, "updated_at": bucket["updated_at"]}


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
    api_key = str(payload.api_key or "").strip() or _tenant_provider_key(app, tenant_id, "openrouter")
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
    try:
        result = await orchestrator.execute(
            goal=payload.goal,
            mode=payload.mode,
            language=payload.language,
            context=payload.context,
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

        async def sink(event: dict[str, Any]) -> None:
            await websocket.send_json({"type": "event", "payload": event})

        result = await orchestrator.execute(
            goal=request.goal,
            mode=request.mode,
            language=request.language,
            context=request.context,
            event_sink=sink,
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

    return WebChatOutboundResponse(
        status="sent",
        result={
            "agent": result.agent,
            "output": result.output,
            "confidence": result.confidence,
            "metadata": result.metadata,
        },
    )


def run() -> None:
    """Console script entrypoint used by `archon-server`."""

    host = os.getenv("ARCHON_HOST", "127.0.0.1")
    port = int(os.getenv("ARCHON_PORT", "8000"))
    uvicorn.run("archon.interfaces.api.server:app", host=host, port=port, reload=False)


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
