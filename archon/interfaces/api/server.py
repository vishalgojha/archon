"""FastAPI server entrypoint for ARCHON runtime APIs."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
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
    try:
        yield
    finally:
        await app.state.orchestrator.aclose()


app = FastAPI(title="ARCHON API", version="0.1.0", lifespan=lifespan)
_exempt_paths = {"/healthz", "/openapi.json", "/docs", "/redoc"}
app.add_middleware(AuthMiddleware, settings=AuthSettings.from_env(), exempt_paths=_exempt_paths)

limiter = create_limiter()
app.state.limiter = limiter
app.state.rate_limit_store = InMemoryTierRateLimitStore.from_env()
set_rate_limit_store(app.state.rate_limit_store)
_rate_limit_handler = cast(
    Callable[[Request, Exception], Response],
    _rate_limit_exceeded_handler,
)
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    """Simple readiness probe endpoint."""

    return {"status": "ok"}


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
