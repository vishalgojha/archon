"""FastAPI server entrypoint for ARCHON runtime APIs."""

import asyncio
import html
import json
import os
import re
import secrets
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi.errors import RateLimitExceeded
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)

from archon.analytics import AnalyticsCollector
from archon.api.auth import TenantTokenError, create_tenant_token
from archon.config import SUPPORTED_PROVIDERS, load_archon_config
from archon.core.approval_gate import (
    ApprovalDeniedError,
    ApprovalRequiredError,
    ApprovalTimeoutError,
)
from archon.core.brain import (
    BrainArtifactError,
    BrainSchemaViolation,
    BrainService,
    BrainUnauthorizedError,
    BrainVersionMismatchError,
    load_brain_config,
    resolve_brain_root,
)
from archon.core.orchestrator import OrchestrationResult, Orchestrator
from archon.interfaces.api.auth import (
    AuthMiddleware,
    AuthSettings,
    decode_auth_token,
    websocket_auth_context,
)
from archon.interfaces.webchat.server import mount_webchat
from archon.interfaces.api.rate_limit import (
    InMemoryTierRateLimitStore,
    create_limiter,
    limit_for_key,
    set_rate_limit_store,
)
from archon.memory.store import MemoryStore as TenantMemoryStore
from archon.providers.router import DEFAULT_BASE_URL, PROVIDER_ENV_KEY
from archon.skills.skill_creator import SkillCreator
from archon.skills.skill_registry import SkillRegistry
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


class SkillProposalRequest(BaseModel):
    """Parameters for proposing a new skill from gaps."""

    limit: int = Field(default=25, ge=1, le=200)
    confidence_threshold: int = Field(default=70, ge=1, le=100)


class DeploymentBranding(BaseModel):
    """Branding options for a deployed agent surface."""

    name: str = Field(min_length=1)
    accent_color: str = Field(default="#6ee7ff")
    logo_url: str | None = None


class DeploymentRequest(BaseModel):
    """Payload for creating a deployment from a workflow."""

    name: str = Field(min_length=1)
    description: str | None = None
    branding: DeploymentBranding
    entry_skill: str = Field(min_length=1)
    workflow: dict[str, Any] = Field(default_factory=dict)
    deployment_id: str | None = None


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


class BrainWriteRequest(BaseModel):
    """Request payload for authoritative brain writes."""

    artifact: Literal["module_registry", "architecture"]
    schema_version: str
    agent_id: str
    payload: dict[str, Any]


class BrainSnapshotRequest(BaseModel):
    """Request payload for non-authoritative brain snapshots."""

    artifact: Literal["reality_snapshot", "delta"]
    payload: dict[str, Any]


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


def _parse_cors_origins(raw: str) -> list[str]:
    return [origin.strip() for origin in str(raw or "").split(",") if origin.strip()]


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
    env_secret = str(os.getenv("ARCHON_JWT_SECRET", "")).strip()
    config_secret = ""
    if not env_secret:
        config_secret = str(getattr(getattr(config, "auth", None), "jwt_secret", "") or "").strip()
    configured_secret = env_secret or config_secret
    if configured_secret:
        app.state.ephemeral_auth = False
    else:
        app.state.ephemeral_auth = True
        if os.getenv("PYTEST_CURRENT_TEST"):
            runtime_secret = "archon-dev-secret-change-me-32-bytes"
        else:
            runtime_secret = secrets.token_urlsafe(48)
        os.environ["ARCHON_JWT_SECRET"] = runtime_secret
    app.state.orchestrator = Orchestrator(config)
    webchat_app = getattr(app.state, "webchat_app", None)
    if isinstance(webchat_app, FastAPI):
        runtime = getattr(webchat_app.state, "runtime", None)
        if runtime is not None:
            runtime.orchestrator = app.state.orchestrator
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
    brain_config = load_brain_config()
    app.state.brain_service = BrainService(brain_config, resolve_brain_root())
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
app.state.webchat_app = mount_webchat(app)
EXEMPT_PREFIXES = {
    "/health",
}
_exempt_paths = {
    "/health",
    "/healthz",
    "/shell",
    "/shell/",
    "/v1/auth/session-token",
}
_exempt_path_prefixes = {
    "/shell/assets",
    "/api",
    "/agent",
    "/ui-packs",
    "/webchat",
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
_default_cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://[::1]:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://[::1]:4173",
]
_cors_origins = _parse_cors_origins(os.getenv("ARCHON_CORS_ORIGINS", ""))
if not _cors_origins:
    _cors_origins = _default_cors_origins
if _cors_origins:
    if "*" in _cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
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


@app.post("/brain/write")
async def brain_write(payload: BrainWriteRequest, request: Request) -> Response:
    """Write an authoritative brain artifact after schema and ownership checks."""

    service: BrainService = request.app.state.brain_service
    try:
        path = service.write(
            artifact=payload.artifact,
            schema_version=payload.schema_version,
            agent_id=payload.agent_id,
            payload=payload.payload,
        )
    except BrainVersionMismatchError as exc:
        return JSONResponse(status_code=422, content={"error": exc.to_error()})
    except BrainUnauthorizedError as exc:
        return JSONResponse(status_code=403, content={"error": exc.to_error()})
    except BrainArtifactError as exc:
        return JSONResponse(status_code=422, content={"error": exc.to_error()})
    except BrainSchemaViolation as exc:
        return JSONResponse(status_code=422, content={"error": exc.to_error()})

    return JSONResponse(
        {
            "artifact": payload.artifact,
            "schema_version": payload.schema_version,
            "authoritative": True,
            "path": str(path),
        }
    )


@app.post("/brain/snapshot")
async def brain_snapshot(payload: BrainSnapshotRequest, request: Request) -> Response:
    """Write a non-authoritative snapshot artifact (no schema or ownership checks)."""

    service: BrainService = request.app.state.brain_service
    try:
        path = service.snapshot(artifact=payload.artifact, payload=payload.payload)
    except BrainArtifactError as exc:
        return JSONResponse(status_code=422, content={"error": exc.to_error()})

    return JSONResponse(
        {
            "artifact": payload.artifact,
            "authoritative": False,
            "note": "Snapshot artifacts are non-authoritative and require planner review.",
            "path": str(path),
        }
    )


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
    client_host = request.url.hostname or ""
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
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
        raise HTTPException(status_code=404, detail="Confirmation request not found.")
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
        raise HTTPException(status_code=404, detail="Confirmation request not found.")
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


@app.get("/api/status")
async def studio_status(request: Request) -> dict[str, Any]:
    """Local studio status snapshot."""

    _require_localhost(request)
    started = float(getattr(app.state, "started_monotonic", time.monotonic()))
    deployments = await asyncio.to_thread(_load_deployments)
    return {
        "status": "ok",
        "version": app.version,
        "git_sha": resolve_git_sha(),
        "uptime_s": max(0.0, time.monotonic() - started),
        "deployment_count": len(deployments),
    }


@app.get("/api/skills")
async def studio_skills(request: Request) -> dict[str, Any]:
    """List registered skills for Studio."""

    _require_localhost(request)
    registry = SkillRegistry()
    skills = [skill.to_dict() for skill in registry.list_skills()]
    return {"skills": skills, "errors": registry.load_errors}


@app.post("/api/skills/propose")
async def studio_skills_propose(
    request: Request,
    payload: SkillProposalRequest,
) -> Response:
    """Propose a skill from recent gap tasks."""

    _require_localhost(request)
    orchestrator: Orchestrator = request.app.state.orchestrator

    async def action(event_sink):
        creator = SkillCreator(
            config=orchestrator.config,
            registry=SkillRegistry(),
            approval_gate=orchestrator.approval_gate,
            audit_trail=orchestrator.audit_trail,
        )
        try:
            gap_tasks = creator.find_gap_tasks(
                limit=payload.limit,
                confidence_threshold=payload.confidence_threshold,
            )
            proposal = await creator.propose_skill(gap_tasks=gap_tasks, event_sink=event_sink)
            if proposal is None:
                return {"status": "no_gaps"}
            return {
                "status": "proposed",
                "skill": proposal.skill.to_dict(),
                "rationale": proposal.rationale,
            }
        finally:
            creator.close()

    if not _is_stream_request(request):
        raise HTTPException(
            status_code=409, detail="Streaming required for approval-gated skill actions."
        )
    return await _stream_action(action)


@app.post("/api/skills/apply/{name}")
async def studio_skills_apply(name: str, request: Request) -> Response:
    """Promote a staging skill after trials."""

    _require_localhost(request)
    orchestrator: Orchestrator = request.app.state.orchestrator

    async def action(event_sink):
        creator = SkillCreator(
            config=orchestrator.config,
            registry=SkillRegistry(),
            approval_gate=orchestrator.approval_gate,
            audit_trail=orchestrator.audit_trail,
        )
        try:
            return await creator.apply_skill(name=name, event_sink=event_sink)
        finally:
            creator.close()

    if not _is_stream_request(request):
        raise HTTPException(
            status_code=409, detail="Streaming required for approval-gated skill actions."
        )
    return await _stream_action(action)


@app.get("/api/providers")
async def studio_providers(request: Request) -> dict[str, Any]:
    """List provider assignments and status."""

    _require_localhost(request)
    orchestrator: Orchestrator = request.app.state.orchestrator
    config = orchestrator.config
    role_names = ("primary", "coding", "vision", "fast", "embedding", "fallback")
    roles = {role: str(getattr(config.byok, role)) for role in role_names}
    provider_names = {value for value in roles.values() if value}
    custom_endpoints = {endpoint.name: endpoint for endpoint in config.byok.custom_endpoints}
    provider_names.update(custom_endpoints.keys())

    providers: list[dict[str, Any]] = []
    for provider in sorted(provider_names):
        assigned_roles = [role for role, value in roles.items() if value == provider]
        if provider in custom_endpoints:
            endpoint = custom_endpoints[provider]
            providers.append(
                {
                    "name": provider,
                    "status": "live",
                    "roles": assigned_roles,
                    "env_key": None,
                    "key_present": None,
                    "key_required": False,
                    "base_url": endpoint.base_url,
                }
            )
            continue
        payload = _provider_status(provider, roles=assigned_roles)
        base_url = DEFAULT_BASE_URL.get(provider)
        if provider == "openrouter":
            base_url = config.byok.openrouter_base_url
        if provider == "ollama":
            base_url = config.byok.ollama_base_url
        payload["base_url"] = base_url
        providers.append(payload)

    return {
        "roles": roles,
        "providers": providers,
    }


class ProviderRoleUpdate(BaseModel):
    provider: str | None = None


@app.patch("/api/providers/{role}")
async def studio_provider_update(
    role: str,
    request: Request,
    payload: ProviderRoleUpdate,
) -> dict[str, Any]:
    """Update provider assignment per role or toggle live mode."""

    _require_localhost(request)
    orchestrator: Orchestrator = request.app.state.orchestrator
    role_key = str(role).strip().lower()
    role_names = ("primary", "coding", "vision", "fast", "embedding", "fallback")
    if role_key not in role_names:
        raise HTTPException(status_code=400, detail="Unknown provider role.")
    provider_raw = str(payload.provider or "").strip()
    provider = provider_raw.lower()
    if not provider:
        raise HTTPException(status_code=400, detail="provider is required.")
    custom_names = {
        endpoint.name.lower(): endpoint.name
        for endpoint in orchestrator.config.byok.custom_endpoints
    }
    if provider not in SUPPORTED_PROVIDERS and provider not in custom_names:
        raise HTTPException(status_code=400, detail="Unsupported provider.")
    provider_value = custom_names.get(provider, provider)
    setattr(orchestrator.config.byok, role_key, provider_value)
    return await studio_providers(request)


@app.get("/api/approvals")
async def studio_list_approvals(request: Request) -> dict[str, Any]:
    """List pending approvals for Studio."""

    _require_localhost(request)
    orchestrator: Orchestrator = request.app.state.orchestrator
    return {"approvals": list(orchestrator.approval_gate.pending_actions)}


@app.post("/api/approvals/{request_id}/approve")
async def studio_approve(
    request_id: str, request: Request, payload: ApprovalActionRequest
) -> dict[str, Any]:
    """Approve a pending Studio approval."""

    _require_localhost(request)
    orchestrator: Orchestrator = request.app.state.orchestrator
    approver = payload.approver or "studio"
    ok = orchestrator.approval_gate.approve(request_id, approver=approver, notes=payload.notes)
    if not ok:
        raise HTTPException(status_code=404, detail="Confirmation request not found.")
    await _emit_analytics_event(
        {
            "tenant_id": "studio",
            "event_type": "approval_granted",
            "request_id": request_id,
            "approver": approver,
        }
    )
    return {"status": "approved", "request_id": request_id}


@app.post("/api/approvals/{request_id}/deny")
async def studio_deny(
    request_id: str, request: Request, payload: ApprovalActionRequest
) -> dict[str, Any]:
    """Deny a pending Studio approval."""

    _require_localhost(request)
    orchestrator: Orchestrator = request.app.state.orchestrator
    approver = payload.approver or "studio"
    ok = orchestrator.approval_gate.deny(request_id, approver=approver, notes=payload.notes)
    if not ok:
        raise HTTPException(status_code=404, detail="Confirmation request not found.")
    await _emit_analytics_event(
        {
            "tenant_id": "studio",
            "event_type": "approval_denied",
            "request_id": request_id,
            "approver": approver,
        }
    )
    return {"status": "denied", "request_id": request_id}


@app.get("/api/tasks")
async def studio_tasks(request: Request, limit: int = 100) -> dict[str, Any]:
    """List recent tasks from the audit trail."""

    _require_localhost(request)
    orchestrator: Orchestrator = request.app.state.orchestrator
    entries = await asyncio.to_thread(
        orchestrator.audit_trail.get_recent_entries,
        limit=min(max(limit, 1), 200),
        event_types=["task_completed", "task_failed"],
    )
    tasks = []
    for entry in entries:
        payload = dict(entry.payload)
        tasks.append(
            {
                "task_id": payload.get("task_id"),
                "goal": payload.get("goal"),
                "mode": payload.get("mode"),
                "status": entry.event_type,
                "confidence": payload.get("confidence"),
                "budget": payload.get("budget"),
                "providers_used": payload.get("providers_used", []),
                "timestamp": entry.timestamp,
            }
        )
    return {"tasks": tasks}


@app.post("/api/tasks")
async def studio_tasks_run(request: Request, payload: TaskRequest) -> Response:
    """Run a task via Studio, optionally streaming events."""

    _require_localhost(request)
    orchestrator: Orchestrator = request.app.state.orchestrator
    context = dict(payload.context)
    context.setdefault("tenant_id", "studio")

    async def action(event_sink):
        async def sink(event: dict[str, Any]) -> None:
            if event_sink:
                await event_sink(event)
            if event.get("type") == "task_completed":
                task_id = str(event.get("task_id") or "")
                routing = orchestrator.provider_router.task_routing_snapshot(task_id)
                if event_sink:
                    await event_sink(
                        {
                            "type": "provider_routing",
                            "task_id": task_id,
                            "providers_used": routing.get("providers", []),
                            "preferred_provider": routing.get("preferred_provider"),
                            "fallback_used": routing.get("fallback_used", False),
                        }
                    )

        result = await orchestrator.execute(
            goal=payload.goal,
            mode=payload.mode,
            language=payload.language,
            context=context,
            event_sink=sink if event_sink else None,
        )
        await _emit_task_analytics(tenant_id="studio", result=result)
        return _to_response(result).model_dump()

    if _is_stream_request(request):
        return await _stream_action(action)

    result = await action(None)
    return JSONResponse(result)


@app.get("/api/evolution/log")
async def studio_evolution_log(
    request: Request,
    limit: int = 200,
    skill: str | None = None,
    provider: str | None = None,
    task: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Filter evolution audit entries."""

    _require_localhost(request)
    orchestrator: Orchestrator = request.app.state.orchestrator
    entries = await asyncio.to_thread(
        orchestrator.audit_trail.get_recent_entries,
        limit=min(max(limit, 1), 500),
    )
    skill_filter = str(skill or "").strip().lower()
    provider_filter = str(provider or "").strip().lower()
    task_filter = str(task or "").strip().lower()
    date_filter = str(date or "").strip()

    start_ts = None
    end_ts = None
    if date_filter:
        try:
            parsed = time.strptime(date_filter, "%Y-%m-%d")
            start_ts = time.mktime(parsed)
            end_ts = start_ts + 86400
        except ValueError:
            start_ts = None
            end_ts = None

    filtered: list[dict[str, Any]] = []
    for entry in entries:
        payload = dict(entry.payload)
        skill_name = str(payload.get("skill", {}).get("name") or payload.get("skill") or "").lower()
        providers_used = [str(item).lower() for item in payload.get("providers_used", [])]
        task_id = str(payload.get("task_id") or "")
        if skill_filter and skill_filter not in skill_name:
            continue
        if provider_filter and provider_filter not in providers_used:
            continue
        if task_filter and task_filter not in task_id and task_filter not in entry.workflow_id:
            continue
        if start_ts is not None and end_ts is not None:
            if not (start_ts <= entry.timestamp < end_ts):
                continue
        filtered.append(
            {
                "entry_id": entry.entry_id,
                "timestamp": entry.timestamp,
                "event_type": entry.event_type,
                "workflow_id": entry.workflow_id,
                "actor": entry.actor,
                "payload": payload,
            }
        )
    return {"entries": filtered}


@app.post("/api/deployments")
async def studio_deployments_create(
    request: Request,
    payload: DeploymentRequest,
) -> Response:
    """Create a deployment config for a workflow."""

    _require_localhost(request)
    orchestrator: Orchestrator = request.app.state.orchestrator

    async def action(event_sink):
        deployments_dir = _ensure_deployments_dir()
        raw_id = payload.deployment_id or payload.name
        cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(raw_id).strip().lower()).strip("-")
        deployment_id = cleaned or f"deploy-{uuid.uuid4().hex[:10]}"
        path = deployments_dir / f"{deployment_id}.json"
        record = {
            "id": deployment_id,
            "name": payload.name,
            "description": payload.description or "",
            "branding": payload.branding.model_dump(),
            "entry_skill": payload.entry_skill,
            "workflow": payload.workflow,
            "created_at": time.time(),
        }
        action_id = f"deployment-write-{uuid.uuid4().hex[:12]}"
        await orchestrator.approval_gate.check(
            "file_write",
            {
                "target": str(path),
                "deployment_id": deployment_id,
                "event_sink": event_sink,
            },
            action_id,
        )
        await asyncio.to_thread(_write_deployment, path, record)
        await _emit_analytics_event(
            {
                "tenant_id": "studio",
                "event_type": "workflow_created",
                "deployment_id": deployment_id,
                "entry_skill": payload.entry_skill,
            }
        )
        return {
            "status": "created",
            "id": deployment_id,
            "url": _deployment_url(deployment_id),
            "path": str(path),
        }

    if not _is_stream_request(request):
        raise HTTPException(
            status_code=409, detail="Streaming required for approval-gated deployment writes."
        )
    return await _stream_action(action)


@app.get("/api/deployments")
async def studio_deployments(request: Request) -> dict[str, Any]:
    """List deployments saved by Studio."""

    _require_localhost(request)
    deployments = await asyncio.to_thread(_load_deployments)
    return {"deployments": [_serialize_deployment(item) for item in deployments]}


@app.get("/api/agent/{deployment_id}")
async def studio_agent(deployment_id: str, request: Request) -> Response:
    """Serve the generated agent UI for a deployment."""

    _require_localhost(request)
    deployment = await asyncio.to_thread(_load_deployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Launch not found.")
    return HTMLResponse(_render_agent_ui(deployment))


@app.get("/agent/{deployment_id}", include_in_schema=False)
async def agent_ui(deployment_id: str, request: Request) -> Response:
    """Friendly alias for the deployment agent UI."""

    return await studio_agent(deployment_id, request)


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


def _is_localhost(request: Request) -> bool:
    host = request.client.host if request.client else ""
    hostname = request.url.hostname or ""
    return host in {"127.0.0.1", "::1", "localhost"} or hostname in {
        "127.0.0.1",
        "::1",
        "localhost",
    }


def _require_localhost(request: Request) -> None:
    if not _is_localhost(request):
        raise HTTPException(status_code=403, detail="Studio endpoints are localhost-only.")


def _is_stream_request(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    if "application/x-ndjson" in accept:
        return True
    raw = str(request.query_params.get("stream", "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _studio_root() -> Path:
    return Path(__file__).resolve().parents[2] / "studio"


def _deployment_dir() -> Path:
    return _studio_root() / "deployments"


def _ensure_deployments_dir() -> Path:
    path = _deployment_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _deployment_url(deployment_id: str) -> str:
    return f"/agent/{deployment_id}"


async def _stream_action(action_coro, *, event_sink=None) -> StreamingResponse:
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def sink(event: dict[str, Any]) -> None:
        payload = {"type": "event", "payload": event, "timestamp": time.time()}
        await queue.put(payload)

    async def runner() -> None:
        try:
            result = await action_coro(event_sink or sink)
            await queue.put({"type": "result", "payload": result, "timestamp": time.time()})
        except (ApprovalDeniedError, ApprovalTimeoutError) as exc:
            await queue.put(
                {
                    "type": "error",
                    "payload": {"message": str(exc), "code": "approval_denied"},
                    "timestamp": time.time(),
                }
            )
        except Exception as exc:  # pragma: no cover - generic guard
            await queue.put(
                {
                    "type": "error",
                    "payload": {"message": str(exc)},
                    "timestamp": time.time(),
                }
            )
        finally:
            await queue.put(None)

    asyncio.create_task(runner())

    async def generator():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield json.dumps(item, separators=(",", ":")) + "\n"

    return StreamingResponse(generator(), media_type="application/x-ndjson")


def _provider_status(
    provider: str,
    *,
    roles: list[str],
) -> dict[str, Any]:
    env_key = PROVIDER_ENV_KEY.get(provider)
    key_required = provider != "ollama"
    key_present = None
    if env_key:
        key_present = bool(os.getenv(env_key))
    status = "live"
    if key_required and key_present is False:
        status = "missing_key"
    return {
        "name": provider,
        "status": status,
        "roles": roles,
        "env_key": env_key,
        "key_present": key_present if key_required else None,
        "key_required": key_required,
        "base_url": DEFAULT_BASE_URL.get(provider),
    }


def _render_agent_ui(deployment: dict[str, Any]) -> str:
    branding = deployment.get("branding") or {}
    name = str(branding.get("name") or deployment.get("name") or "Agent")
    accent = str(branding.get("accent_color") or "#6ee7ff")
    logo_url = str(branding.get("logo_url") or "")
    deployment_id = str(deployment.get("id") or "")
    entry_skill = str(deployment.get("entry_skill") or "")
    safe_name = html.escape(name)
    safe_accent = html.escape(accent)
    safe_logo_url = html.escape(logo_url, quote=True)
    safe_deployment_id = json.dumps(deployment_id)
    safe_entry_skill = json.dumps(entry_skill)
    logo_markup = (
        f'<img class="logo" src="{safe_logo_url}" alt="{safe_name}" />' if logo_url else ""
    )
    return f"""
<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"UTF-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <title>{safe_name}</title>
    <style>
      :root {{
        color-scheme: dark;
        --bg: #0b1118;
        --panel: #101826;
        --text: #e6edf3;
        --muted: #9fb0c4;
        --accent: {safe_accent};
        font-family: \"Space Grotesk\", system-ui, sans-serif;
      }}
      body {{
        margin: 0;
        background: radial-gradient(circle at top, rgba(60, 192, 255, 0.12), transparent 40%), var(--bg);
        color: var(--text);
      }}
      .shell {{
        max-width: 860px;
        margin: 40px auto;
        padding: 24px;
      }}
      .card {{
        background: var(--panel);
        border: 1px solid rgba(148, 163, 184, 0.2);
        border-radius: 20px;
        padding: 24px;
        box-shadow: 0 24px 40px rgba(0,0,0,0.4);
      }}
      .header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
      }}
      .logo {{
        width: 42px;
        height: 42px;
        border-radius: 12px;
        object-fit: cover;
        border: 1px solid rgba(148, 163, 184, 0.3);
      }}
      .messages {{
        margin-top: 24px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        max-height: 460px;
        overflow-y: auto;
      }}
      .message {{
        padding: 12px 16px;
        border-radius: 16px;
        border: 1px solid rgba(148, 163, 184, 0.2);
        background: rgba(15, 23, 42, 0.6);
        font-size: 14px;
        line-height: 1.5;
      }}
      .message.user {{
        border-color: var(--accent);
        background: rgba(56, 189, 248, 0.1);
      }}
      .composer {{
        margin-top: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }}
      textarea {{
        resize: vertical;
        min-height: 90px;
        border-radius: 14px;
        border: 1px solid rgba(148, 163, 184, 0.3);
        background: rgba(15, 23, 42, 0.8);
        color: var(--text);
        padding: 12px;
        font-size: 14px;
      }}
      button {{
        align-self: flex-end;
        background: var(--accent);
        color: #0b1118;
        border: none;
        border-radius: 999px;
        padding: 10px 18px;
        font-weight: 600;
        cursor: pointer;
      }}
      .approval {{
        display: flex;
        gap: 8px;
        margin-top: 8px;
      }}
      .approval button {{
        background: transparent;
        border: 1px solid rgba(148, 163, 184, 0.4);
        color: var(--text);
      }}
      .approval button.primary {{
        background: var(--accent);
        color: #0b1118;
        border: none;
      }}
      .muted {{
        color: var(--muted);
        font-size: 12px;
      }}
    </style>
  </head>
  <body>
    <div class=\"shell\">
      <div class=\"card\">
        <div class=\"header\">
          <div>
            <div class=\"muted\">Live agent</div>
            <h1>{safe_name}</h1>
          </div>
          {logo_markup}
        </div>
        <div id=\"messages\" class=\"messages\"></div>
        <div class=\"composer\">
          <textarea id=\"input\" placeholder=\"Describe your goal\"></textarea>
          <button id=\"send\">Send</button>
        </div>
      </div>
    </div>
    <script>
      const messages = document.getElementById(\"messages\");\n
      const input = document.getElementById(\"input\");\n
      const send = document.getElementById(\"send\");\n
      function addMessage(text, role) {{\n
        const div = document.createElement(\"div\");\n
        div.className = \"message \" + (role || \"system\");\n
        div.textContent = text;\n
        messages.appendChild(div);\n
        messages.scrollTop = messages.scrollHeight;\n
      }}\n
      function addApproval(meta) {{\n
        const wrap = document.createElement(\"div\");\n
        wrap.className = \"message\";\n
        wrap.textContent = \"Confirmation needed.\";\n
        const actions = document.createElement(\"div\");\n
        actions.className = \"approval\";\n
        const approve = document.createElement(\"button\");\n
        approve.className = \"primary\";\n
        approve.textContent = \"Confirm\";\n
        approve.onclick = () => respond(true, meta.request_id);\n
        const deny = document.createElement(\"button\");\n
        deny.textContent = \"Decline\";\n
        deny.onclick = () => respond(false, meta.request_id);\n
        actions.appendChild(approve);\n
        actions.appendChild(deny);\n
        wrap.appendChild(actions);\n
        messages.appendChild(wrap);\n
      }}\n
      async function respond(approve, id) {{\n
        const path = approve ? \"/api/approvals/\" + id + \"/approve\" : \"/api/approvals/\" + id + \"/deny\";\n
        await fetch(path, {{ method: \"POST\", headers: {{ \"Content-Type\": \"application/json\" }}, body: JSON.stringify({{ approver: \"agent-ui\" }}) }});\n
      }}\n
      async function runTask(goal) {{\n
        const response = await fetch(\"/api/tasks?stream=1\", {{\n
          method: \"POST\",\n
          headers: {{ \"Content-Type\": \"application/json\", \"Accept\": \"application/x-ndjson\" }},\n
          body: JSON.stringify({{ goal, mode: \"debate\", context: {{ deployment_id: {safe_deployment_id}, entry_skill: {safe_entry_skill} }} }})\n
        }});\n
        const reader = response.body.getReader();\n
        const decoder = new TextDecoder();\n
        let buffer = \"\";\n
        while (true) {{\n
          const {{ value, done }} = await reader.read();\n
          if (done) break;\n
          buffer += decoder.decode(value, {{ stream: true }});\n
          let boundary = buffer.indexOf(\"\\n\");\n
          while (boundary !== -1) {{\n
            const line = buffer.slice(0, boundary).trim();\n
            buffer = buffer.slice(boundary + 1);\n
            if (line) {{\n
              const payload = JSON.parse(line);\n
              if (payload.type === \"event\") {{\n
                if (payload.payload?.type === \"approval_required\") {{\n
                  addApproval(payload.payload);\n
                }} else {{\n
                  addMessage(payload.payload?.type || \"event\", \"system\");\n
                }}\n
              }}\n
              if (payload.type === \"result\") {{\n
                addMessage(payload.payload?.final_answer || \"Completed.\", \"assistant\");\n
              }}\n
            }}\n
            boundary = buffer.indexOf(\"\\n\");\n
          }}\n
        }}\n
      }}\n
      send.addEventListener(\"click\", () => {{\n
        const goal = input.value.trim();\n
        if (!goal) return;\n
        addMessage(goal, \"user\");\n
        input.value = \"\";\n
        runTask(goal);\n
      }});\n
    </script>
  </body>
</html>
    """


def _write_deployment(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_deployment(deployment_id: str) -> dict[str, Any] | None:
    path = _deployment_dir() / f"{deployment_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_deployments() -> list[dict[str, Any]]:
    deployments_dir = _ensure_deployments_dir()
    deployments: list[dict[str, Any]] = []
    for path in sorted(deployments_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payload.setdefault("id", path.stem)
            deployments.append(payload)
    return deployments


def _serialize_deployment(payload: dict[str, Any]) -> dict[str, Any]:
    deployment_id = str(payload.get("id") or "")
    return {
        "id": deployment_id,
        "name": payload.get("name"),
        "description": payload.get("description"),
        "entry_skill": payload.get("entry_skill"),
        "created_at": payload.get("created_at"),
        "url": _deployment_url(deployment_id),
    }


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
