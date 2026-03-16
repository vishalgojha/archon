"""FastAPI server entrypoint for ARCHON runtime APIs."""

import asyncio
import os
import secrets
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi.errors import RateLimitExceeded
from starlette.responses import FileResponse, JSONResponse, Response

from archon.analytics import AnalyticsCollector
from archon.api.auth import TenantTokenError, create_tenant_token
from archon.config import load_archon_config
from archon.core.approval_gate import ApprovalRequiredError
from archon.core.orchestrator import OrchestrationResult, Orchestrator
from archon.interfaces.api.auth import (
    AuthMiddleware,
    AuthSettings,
    decode_auth_token,
    websocket_auth_context,
)
from archon.interfaces.api.rate_limit import (
    InMemoryTierRateLimitStore,
    create_limiter,
    limit_for_key,
    set_rate_limit_store,
)
from archon.memory.store import MemoryStore as TenantMemoryStore
from archon.ui_packs.builder import UIPackBuildResult, build_pack
from archon.ui_packs.registry import UIPackRegistry
from archon.ui_packs.storage import UIPackError, UIPackStorage
from archon.versioning import resolve_git_sha, resolve_version


class TaskRequest(BaseModel):
    """Task request accepted by HTTP and WebSocket APIs."""

    goal: str = Field(min_length=1)
    mode: Literal["debate"] = "debate"
    language: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    """JSON-safe API response for completed orchestration tasks."""

    task_id: str
    goal: str
    mode: Literal["debate"]
    final_answer: str
    confidence: int
    budget: dict[str, Any]
    debate: dict[str, Any] | None = None


class ApprovalActionRequest(BaseModel):
    """Payload for approving or denying a pending guarded action."""

    approver: str | None = None
    notes: str | None = None


class UIPackRegisterRequest(BaseModel):
    """Payload for registering a UI pack version.

    Example:
        >>> UIPackRegisterRequest(version="v1").version
        'v1'
    """

    version: str = Field(min_length=1)
    auto_approve: bool = False


class UIPackActivateRequest(BaseModel):
    """Payload for activating a UI pack version.

    Example:
        >>> UIPackActivateRequest(version="v1").version
        'v1'
    """

    version: str = Field(min_length=1)
    auto_approve: bool = False


class UIPackBuildRequest(BaseModel):
    """Payload for building a UI pack from a blueprint.

    Example:
        >>> UIPackBuildRequest(version="v1", blueprint={"title": "Studio"}).version
        'v1'
    """

    version: str = Field(min_length=1)
    blueprint: dict[str, Any] = Field(default_factory=dict)
    auto_approve: bool = False


class SessionTokenRequest(BaseModel):
    """Request for issuing an ephemeral session token.

    Example:
        >>> SessionTokenRequest(tenant_id="demo", tier="pro", expires_in=3600)
    """

    tenant_id: str | None = None
    tier: str | None = None
    expires_in: int = Field(default=3600, ge=60, le=7 * 24 * 3600)


def _to_response(result: OrchestrationResult) -> TaskResponse:
    return TaskResponse(
        task_id=result.task_id,
        goal=result.goal,
        mode=result.mode,
        final_answer=result.final_answer,
        confidence=result.confidence,
        budget=result.budget,
        debate=result.debate,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    test_tmp_dir = None
    test_db_root: Path | None = None
    if os.getenv("PYTEST_CURRENT_TEST"):
        test_tmp_dir = tempfile.TemporaryDirectory(prefix="archon-test-")
        test_db_root = Path(test_tmp_dir.name)
        app.state._test_tmp_dir = test_tmp_dir

    def _db_path(env_var: str, default_name: str) -> str:
        env_value = os.getenv(env_var)
        if env_value:
            return env_value
        if test_db_root is not None:
            return str(test_db_root / default_name)
        return default_name

    config_path = os.getenv("ARCHON_CONFIG", "config.archon.yaml")
    config = load_archon_config(config_path)
    secret = str(os.getenv("ARCHON_JWT_SECRET", "")).strip()
    if not secret:
        secret = str(getattr(getattr(config, "auth", None), "jwt_secret", "") or "").strip()
    if not secret and os.getenv("PYTEST_CURRENT_TEST"):
        secret = "archon-dev-secret-change-me-32-bytes"
    if not secret:
        secret = secrets.token_urlsafe(48)
        os.environ["ARCHON_JWT_SECRET"] = secret
        app.state.ephemeral_auth = True
    else:
        app.state.ephemeral_auth = False
    app.state.orchestrator = Orchestrator(config)
    app.state.auth_settings = AuthSettings.from_env(config)
    app.state.analytics_collector = AnalyticsCollector(
        path=_db_path("ARCHON_ANALYTICS_DB", "archon_analytics.sqlite3")
    )
    app.state.tenant_memory_store = TenantMemoryStore(
        db_path=_db_path("ARCHON_MEMORY_DB", "archon_memory.sqlite3")
    )
    app.state.ui_pack_registry = UIPackRegistry(
        path=_db_path("ARCHON_UI_PACK_DB", "archon_ui_packs.sqlite3")
    )
    app.state.ui_pack_storage = UIPackStorage(root=os.getenv("ARCHON_UI_PACK_ROOT", "ui_packs"))
    app.state.started_monotonic = time.monotonic()
    try:
        yield
    finally:
        tenant_memory_store = getattr(app.state, "tenant_memory_store", None)
        if isinstance(tenant_memory_store, TenantMemoryStore):
            tenant_memory_store.close()
        await app.state.orchestrator.aclose()
        if test_tmp_dir is not None:
            test_tmp_dir.cleanup()


app = FastAPI(title="ARCHON API", version=resolve_version(), lifespan=lifespan)
EXEMPT_PREFIXES = {
    "/health",
}
_exempt_paths = {
    "/health",
    "/healthz",
    "/shell",
    "/shell/",
}
_exempt_path_prefixes = {
    "/shell/assets",
    "/ui-packs",
    *EXEMPT_PREFIXES,
}
app.add_middleware(
    AuthMiddleware,
    settings=AuthSettings.from_env(
        load_archon_config(os.getenv("ARCHON_CONFIG", "config.archon.yaml"))
    ),
    exempt_paths=_exempt_paths,
    exempt_path_prefixes=_exempt_path_prefixes,
)

limiter = create_limiter()
app.state.limiter = limiter
app.state.rate_limit_store = InMemoryTierRateLimitStore.from_env()
set_rate_limit_store(app.state.rate_limit_store)
app.state.started_monotonic = time.monotonic()

_shell_static_dir = Path(__file__).resolve().parents[1] / "web" / "shell"
if _shell_static_dir.exists():
    app.mount(
        "/shell/assets",
        StaticFiles(directory=str(_shell_static_dir)),
        name="shell-assets",
    )


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> Response:
    del request
    return JSONResponse({"error": f"Rate limit exceeded: {exc.detail}"}, status_code=429)


@app.get("/shell", include_in_schema=False)
@app.get("/shell/", include_in_schema=False)
async def shell_index() -> Response:
    """Serve the self-evolving shell UI."""

    if not _shell_static_dir.exists():
        raise HTTPException(status_code=404, detail="Shell UI is unavailable.")
    return FileResponse(_shell_static_dir / "index.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    """Runtime health with version and uptime."""

    started = float(getattr(app.state, "started_monotonic", time.monotonic()))
    return {
        "status": "ok",
        "version": app.version,
        "git_sha": resolve_git_sha(),
        "uptime_s": max(0.0, time.monotonic() - started),
    }


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    """Simple readiness probe endpoint."""

    return {"status": "ok"}


@app.post("/v1/auth/session-token")
async def issue_session_token(payload: SessionTokenRequest, request: Request) -> dict[str, Any]:
    """Issue an ephemeral session token when no JWT secret is configured.

    Example:
        >>> # POST /v1/auth/session-token
        >>> {"token": "...", "tenant_id": "session-abc123", "tier": "pro"}
    """

    if not bool(getattr(request.app.state, "ephemeral_auth", False)):
        raise HTTPException(
            status_code=403,
            detail="Session token issuance is disabled when JWT secret is configured.",
        )
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="Session token endpoint is localhost-only.")

    tenant_id = str(payload.tenant_id or "").strip() or f"session-{uuid.uuid4().hex[:10]}"
    tier = str(payload.tier or "").strip().lower() or "pro"
    expires_in = int(payload.expires_in or 3600)
    settings = getattr(request.app.state, "auth_settings", None)
    secret = settings.secret if isinstance(settings, AuthSettings) else None
    try:
        token = create_tenant_token(
            tenant_id=tenant_id,
            tier=tier,  # type: ignore[arg-type]
            expires_in_seconds=expires_in,
            secret=secret,
        )
    except TenantTokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _emit_analytics_event(
        {
            "tenant_id": tenant_id,
            "event_type": "auth_session_token_issued",
            "tier": tier,
            "expires_in": expires_in,
            "ephemeral": True,
        }
    )

    return {
        "token": token,
        "tenant_id": tenant_id,
        "tier": tier,
        "expires_in": expires_in,
        "ephemeral": True,
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
    return {"status": "approved", "request_id": request_id}


@app.get("/v1/approvals")
@limiter.limit(limit_for_key)
async def list_pending_approvals(request: Request) -> dict[str, Any]:
    """List pending approvals for the authenticated tenant.

    Example:
        >>> isinstance(list_pending_approvals, object)
        True
    """

    orchestrator: Orchestrator = app.state.orchestrator
    gate = orchestrator.approval_gate
    tenant_id = request.state.auth.tenant_id
    approvals = []
    for row in gate.pending_actions:
        context = row.get("context", {}) if isinstance(row, dict) else {}
        if not isinstance(context, dict):
            continue
        if str(context.get("tenant_id", "")).strip() != tenant_id:
            continue
        created_at = float(row.get("created_at", time.time()))
        approvals.append(
            {
                "request_id": str(row.get("action_id") or ""),
                "action_id": str(row.get("action_id") or ""),
                "action": str(row.get("action") or ""),
                "risk_level": row.get("risk_level"),
                "created_at": created_at,
                "context": dict(context),
                "timeout_remaining_s": _approval_timeout_remaining(created_at, gate=gate),
            }
        )
    return {"approvals": approvals}


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
    return {"status": "denied", "request_id": request_id}


@app.post("/v1/ui-packs/build")
@limiter.limit(limit_for_key)
async def build_ui_pack(request: Request, payload: UIPackBuildRequest) -> dict[str, Any]:
    """Build a UI pack from a blueprint after approval.

    Example:
        >>> isinstance(build_ui_pack, object)
        True
    """

    tenant_id = request.state.auth.tenant_id
    orchestrator: Orchestrator = app.state.orchestrator
    gate = orchestrator.approval_gate
    action_id = f"ui-pack-build-{uuid.uuid4().hex[:12]}"
    sink = None
    if payload.auto_approve:
        approver = tenant_id

        async def sink(event: dict[str, Any]) -> None:
            if event.get("type") == "approval_required":
                gate.approve(
                    str(event["request_id"]),
                    approver=approver,
                    notes="Auto-approved by authenticated operator via REST.",
                )

    try:
        await gate.check(
            "ui_pack_build",
            {
                "tenant_id": tenant_id,
                "version": payload.version,
                "event_sink": sink,
            },
            action_id,
        )
    except ApprovalRequiredError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"{exc} Use approval flow or set auto_approve=true.",
        ) from exc

    storage: UIPackStorage = app.state.ui_pack_storage
    try:
        result: UIPackBuildResult = await asyncio.to_thread(
            build_pack,
            tenant_id=tenant_id,
            version=payload.version,
            blueprint=payload.blueprint,
            storage=storage,
            created_by=tenant_id,
        )
    except UIPackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _emit_analytics_event(
        {
            "tenant_id": tenant_id,
            "event_type": "ui_pack_build",
            "version": payload.version,
        }
    )
    return {
        "status": "built",
        "version": payload.version,
        "pack_dir": str(result.pack_dir),
        "assets": result.assets,
    }


@app.get("/v1/ui-packs/active")
@limiter.limit(limit_for_key)
async def get_active_ui_pack(request: Request) -> dict[str, Any]:
    """Return the active UI pack for the authenticated tenant.

    Example:
        >>> isinstance(get_active_ui_pack, object)
        True
    """

    registry: UIPackRegistry = app.state.ui_pack_registry
    tenant_id = request.state.auth.tenant_id
    active = registry.get_active_pack(tenant_id)
    if active is None:
        return {"status": "none", "active": None}
    return {
        "status": "ok",
        "active": _ui_pack_payload(active),
        "asset_base": _ui_pack_asset_base(active.version),
    }


@app.get("/v1/ui-packs/versions")
@limiter.limit(limit_for_key)
async def list_ui_pack_versions(request: Request) -> dict[str, Any]:
    """List registered UI pack versions for the authenticated tenant.

    Example:
        >>> isinstance(list_ui_pack_versions, object)
        True
    """

    registry: UIPackRegistry = app.state.ui_pack_registry
    tenant_id = request.state.auth.tenant_id
    return {"versions": registry.list_versions(tenant_id)}


@app.post("/v1/ui-packs/register")
@limiter.limit(limit_for_key)
async def register_ui_pack(
    request: Request,
    payload: UIPackRegisterRequest,
) -> dict[str, Any]:
    """Register a UI pack version from storage after approval.

    Example:
        >>> isinstance(register_ui_pack, object)
        True
    """

    tenant_id = request.state.auth.tenant_id
    orchestrator: Orchestrator = app.state.orchestrator
    gate = orchestrator.approval_gate
    action_id = f"ui-pack-publish-{uuid.uuid4().hex[:12]}"
    sink = None
    if payload.auto_approve:
        approver = tenant_id

        async def sink(event: dict[str, Any]) -> None:
            if event.get("type") == "approval_required":
                gate.approve(
                    str(event["request_id"]),
                    approver=approver,
                    notes="Auto-approved by authenticated operator via REST.",
                )

    try:
        await gate.check(
            "ui_pack_publish",
            {
                "tenant_id": tenant_id,
                "version": payload.version,
                "event_sink": sink,
            },
            action_id,
        )
    except ApprovalRequiredError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"{exc} Use approval flow or set auto_approve=true.",
        ) from exc

    storage: UIPackStorage = app.state.ui_pack_storage
    registry: UIPackRegistry = app.state.ui_pack_registry
    try:
        descriptor = await asyncio.to_thread(storage.load_descriptor, tenant_id, payload.version)
        failures = await asyncio.to_thread(storage.verify_assets, descriptor)
        if failures:
            raise HTTPException(
                status_code=400,
                detail={"error": "asset_integrity_failed", "assets": failures},
            )
        metadata = registry.register_pack(descriptor=descriptor, created_by=tenant_id)
    except UIPackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await _emit_analytics_event(
        {
            "tenant_id": tenant_id,
            "event_type": "ui_pack_publish",
            "version": metadata.version,
            "digest": metadata.digest,
        }
    )
    return {
        "status": "registered",
        "pack": _ui_pack_payload(metadata),
        "asset_base": _ui_pack_asset_base(metadata.version),
    }


@app.post("/v1/ui-packs/activate")
@limiter.limit(limit_for_key)
async def activate_ui_pack(
    request: Request,
    payload: UIPackActivateRequest,
) -> dict[str, Any]:
    """Activate a registered UI pack version after approval.

    Example:
        >>> isinstance(activate_ui_pack, object)
        True
    """

    tenant_id = request.state.auth.tenant_id
    orchestrator: Orchestrator = app.state.orchestrator
    gate = orchestrator.approval_gate
    action_id = f"ui-pack-activate-{uuid.uuid4().hex[:12]}"
    sink = None
    if payload.auto_approve:
        approver = tenant_id

        async def sink(event: dict[str, Any]) -> None:
            if event.get("type") == "approval_required":
                gate.approve(
                    str(event["request_id"]),
                    approver=approver,
                    notes="Auto-approved by authenticated operator via REST.",
                )

    try:
        await gate.check(
            "ui_pack_activate",
            {
                "tenant_id": tenant_id,
                "version": payload.version,
                "event_sink": sink,
            },
            action_id,
        )
    except ApprovalRequiredError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"{exc} Use approval flow or set auto_approve=true.",
        ) from exc

    registry: UIPackRegistry = app.state.ui_pack_registry
    try:
        metadata = registry.set_active_version(
            tenant_id=tenant_id, version=payload.version, updated_by=tenant_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await _emit_analytics_event(
        {
            "tenant_id": tenant_id,
            "event_type": "ui_pack_activate",
            "version": metadata.version,
            "digest": metadata.digest,
        }
    )
    return {
        "status": "active",
        "pack": _ui_pack_payload(metadata),
        "asset_base": _ui_pack_asset_base(metadata.version),
    }


@app.get("/ui-packs/{version}/{asset_path:path}", include_in_schema=False)
async def ui_pack_asset(version: str, asset_path: str, request: Request) -> Response:
    """Serve a UI pack asset using token query auth."""

    auth = _ui_pack_auth_context(request)
    registry: UIPackRegistry = app.state.ui_pack_registry
    active = registry.get_active_pack(auth.tenant_id)
    if active is None or active.version != version:
        raise HTTPException(status_code=404, detail="UI pack version is not active.")

    storage: UIPackStorage = app.state.ui_pack_storage
    try:
        descriptor = await asyncio.to_thread(storage.load_descriptor, auth.tenant_id, version)
        if asset_path not in descriptor.assets:
            raise HTTPException(status_code=404, detail="Asset not found.")
        resolved = storage.resolve_asset_path(descriptor, asset_path)
    except UIPackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content_type = str(descriptor.assets.get(asset_path, {}).get("content_type") or "").strip()
    return FileResponse(resolved, media_type=content_type or None)


def _approval_timeout_remaining(created_at: float, *, gate) -> float:
    default_timeout = float(getattr(gate, "default_timeout_seconds", 120.0))
    elapsed = max(0.0, time.time() - float(created_at))
    return max(0.0, default_timeout - elapsed)


def _ui_pack_asset_base(version: str) -> str:
    return f"/ui-packs/{version}"


def _ui_pack_payload(metadata) -> dict[str, Any]:
    return {
        "tenant_id": metadata.tenant_id,
        "version": metadata.version,
        "entrypoint": metadata.entrypoint,
        "digest": metadata.digest,
        "created_at": metadata.created_at,
        "created_by": metadata.created_by,
        "schema_version": metadata.schema_version,
        "manifest": metadata.manifest,
        "metadata": metadata.metadata,
    }


def _ui_pack_auth_context(request: Request):
    auth_header = request.headers.get("authorization")
    token = None
    if auth_header:
        parts = auth_header.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
    if not token:
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing UI pack token.")
    settings: AuthSettings = app.state.auth_settings
    return decode_auth_token(token, settings)


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


async def _emit_task_analytics(*, tenant_id: str, result: OrchestrationResult) -> None:
    payload = {
        "tenant_id": tenant_id,
        "event_type": "task_completed",
        "task_id": result.task_id,
        "mode": result.mode,
        "confidence": result.confidence,
        "cost_usd": result.budget.get("total_cost_usd", 0),
    }
    await _emit_analytics_event(payload)


def _mask_token(value: str) -> str:
    cleaned = str(value or "")
    if len(cleaned) <= 8:
        return "*" * len(cleaned)
    return f"{cleaned[:4]}***{cleaned[-4:]}"


def run() -> None:
    """Run the ARCHON API server with env-configured host/port."""

    uvicorn.run(
        "archon.interfaces.api.server:app",
        host=os.getenv("ARCHON_HOST", "0.0.0.0"),
        port=int(os.getenv("ARCHON_PORT", "8000")),
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":  # pragma: no cover
    run()
