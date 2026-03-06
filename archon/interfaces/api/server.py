"""FastAPI server entrypoint for ARCHON runtime APIs."""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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
