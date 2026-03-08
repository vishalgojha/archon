"""FastAPI sub-application for ARCHON webchat endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from archon.analytics.aggregator import AnalyticsAggregator
from archon.analytics.collector import AnalyticsCollector
from archon.core.orchestrator import Orchestrator
from archon.interfaces.webchat.auth import (
    WebChatTokenError,
    create_anonymous_token,
    create_identified_token,
    verify_webchat_token,
)
from archon.interfaces.webchat.session_store import (
    DEFAULT_SQLITE_PATH,
    AbstractSessionStore,
    Message,
    SessionState,
    create_session_store,
)
from archon.mobile.sync_store import MobileSyncPage, MobileSyncStore
from archon.multimodal import (
    AudioInput,
    AudioProcessor,
    ImageInput,
    ImageProcessor,
    MultimodalOrchestrator,
)
from archon.notifications.device_registry import DeviceRegistry
from archon.notifications.push import PushNotifier
from archon.vernacular.streaming import StreamingTranslator
from archon.versioning import resolve_version

log = logging.getLogger(__name__)


@dataclass(slots=True)
class WebChatRuntime:
    """Dependencies bound to one webchat app instance.

    Example:
        >>> runtime = WebChatRuntime(session_store=create_session_store("memory"))
        >>> runtime.orchestrator is None
        True
    """

    session_store: AbstractSessionStore
    orchestrator: Orchestrator | None = None
    analytics_collector: AnalyticsCollector | None = None
    mobile_sync_store: MobileSyncStore | None = None
    device_registry: DeviceRegistry | None = None
    push_notifier: PushNotifier | None = None


class CreateTokenRequest(BaseModel):
    """Token creation payload."""

    session_id: str | None = None


class UpgradeTokenRequest(BaseModel):
    """Anonymous-to-identified upgrade payload."""

    token: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    tier: str = Field(min_length=1)


class RegisterMobileDeviceRequest(BaseModel):
    """Mobile push token registration payload."""

    token: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    device_token: str = Field(min_length=1)


def create_webchat_app(
    *,
    session_store: AbstractSessionStore | None = None,
    orchestrator: Orchestrator | None = None,
) -> FastAPI:
    """Create the webchat FastAPI sub-app.

    Example:
        >>> app = create_webchat_app()
        >>> isinstance(app, FastAPI)
        True
    """

    app = FastAPI(title="ARCHON WebChat", version=resolve_version())
    app.state.runtime = WebChatRuntime(
        session_store=session_store or _build_default_store(),
        orchestrator=orchestrator,
    )
    static_dir = Path(__file__).with_name("static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="webchat-static")

    @app.post("/token")
    async def create_token(payload: CreateTokenRequest) -> dict[str, Any]:
        """Create anonymous token and pre-create session.

        Example:
            >>> # POST /webchat/token
            >>> True
            True
        """

        log.info("POST /webchat/token called")
        runtime = _runtime(app)
        session_id = (payload.session_id or f"session-{uuid.uuid4().hex[:12]}").strip()
        if not session_id:
            raise HTTPException(status_code=422, detail="session_id cannot be empty.")
        identity = create_anonymous_token(session_id)
        session = SessionState(
            session_id=session_id,
            tenant_id=identity.tenant_id,
            tier=identity.tier,
            metadata={"anonymous": True},
        )
        saved = await runtime.session_store.create_session(session)
        return {
            "token": identity.token,
            "identity": identity.to_dict(),
            "session": saved.to_dict(),
        }

    @app.post("/upgrade")
    async def upgrade_token(payload: UpgradeTokenRequest) -> dict[str, Any]:
        """Upgrade anonymous session identity to identified tenant identity.

        Example:
            >>> # POST /webchat/upgrade
            >>> True
            True
        """

        runtime = _runtime(app)
        current = verify_webchat_token(payload.token)
        if not current.is_anonymous:
            raise HTTPException(status_code=403, detail="Only anonymous tokens can be upgraded.")

        upgraded = create_identified_token(
            tenant_id=payload.tenant_id,
            tier=payload.tier,
            session_id=current.session_id,
        )
        existing = await runtime.session_store.get_session(current.session_id)
        if existing is None:
            await runtime.session_store.create_session(
                SessionState(
                    session_id=current.session_id,
                    tenant_id=upgraded.tenant_id,
                    tier=upgraded.tier,
                    metadata={"anonymous": False},
                )
            )
        else:
            existing.tenant_id = upgraded.tenant_id
            existing.tier = upgraded.tier
            existing.metadata["anonymous"] = False
            await runtime.session_store.update_session(existing)
        return {"token": upgraded.token, "identity": upgraded.to_dict()}

    @app.get("/session/{session_id}")
    async def get_session_summary(
        session_id: str,
        token: str = Query(..., min_length=1),
    ) -> dict[str, Any]:
        """Return session metadata and last 10 messages.

        Example:
            >>> # GET /webchat/session/{id}?token=...
            >>> True
            True
        """

        runtime = _runtime(app)
        identity = _verify_token_or_401(token)
        _authorize_session(identity.session_id, session_id)
        session = await runtime.session_store.get_session(session_id)
        if session is None:
            session = await runtime.session_store.create_session(
                SessionState(
                    session_id=session_id, tenant_id=identity.tenant_id, tier=identity.tier
                )
            )
        rows = await runtime.session_store.get_messages(session_id, last_n=10)
        return {
            "session": session.to_dict(),
            "messages": [row.to_dict() for row in rows],
            "message_count": len(rows),
        }

    @app.post("/mobile/devices")
    async def register_mobile_device(payload: RegisterMobileDeviceRequest) -> dict[str, Any]:
        """Register one mobile push device to the current tenant.

        Example:
            >>> # POST /webchat/mobile/devices
            >>> True
            True
        """

        runtime = _runtime(app)
        identity = _verify_token_or_401(payload.token)
        if runtime.device_registry is None:
            raise HTTPException(status_code=503, detail="Mobile device registry unavailable.")
        row = runtime.device_registry.register(
            tenant_id=identity.tenant_id,
            platform=payload.platform,
            token=payload.device_token,
        )
        if runtime.analytics_collector is not None:
            runtime.analytics_collector.record(
                tenant_id=identity.tenant_id,
                event_type="state_change",
                properties={
                    "action": "mobile_device_registered",
                    "platform": row.platform,
                    "token_id": row.token_id,
                    "session_id": identity.session_id,
                },
            )
        return {
            "status": "registered",
            "token_id": row.token_id,
            "platform": row.platform,
            "tenant_id": row.tenant_id,
            "session_id": identity.session_id,
        }

    @app.get("/mobile/sync/{session_id}")
    async def mobile_sync(
        session_id: str,
        token: str = Query(..., min_length=1),
        since: float = Query(default=0.0),
        cursor: str | None = Query(default=None),
        page_size: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, Any]:
        """Return incremental mobile sync data for one authenticated session.

        Example:
            >>> # GET /webchat/mobile/sync/{session_id}?token=...
            >>> True
            True
        """

        runtime = _runtime(app)
        identity = _verify_token_or_401(token)
        _authorize_session(identity.session_id, session_id)
        page = (
            runtime.mobile_sync_store.list_events(
                identity.tenant_id,
                since=since,
                cursor=cursor,
                limit=page_size,
            )
            if runtime.mobile_sync_store is not None
            else MobileSyncPage(
                events=[],
                next_cursor=None,
                has_more=False,
                watermark=max(0.0, float(since or 0.0)),
                stale_watermark_recovered=False,
            )
        )
        pending = _pending_approvals_for_tenant(runtime, identity.tenant_id)
        summary = _dashboard_summary(runtime, identity.tenant_id)
        summary["pending_approvals"] = len(pending)
        summary["notifications"] = len(page.events)
        return {
            "session_id": identity.session_id,
            "tenant_id": identity.tenant_id,
            "notifications": [row.to_dict() for row in page.events],
            "pending_approvals": pending,
            "dashboard_summary": summary,
            "sync": {
                "watermark": page.watermark,
                "next_cursor": page.next_cursor,
                "has_more": page.has_more,
                "stale_watermark_recovered": page.stale_watermark_recovered,
                "page_size": page_size,
                "server_time": time.time(),
            },
        }

    @app.delete("/session/{session_id}")
    async def clear_session_messages(
        session_id: str,
        token: str = Query(..., min_length=1),
    ) -> dict[str, Any]:
        """Clear all messages in one session.

        Example:
            >>> # DELETE /webchat/session/{id}?token=...
            >>> True
            True
        """

        runtime = _runtime(app)
        identity = _verify_token_or_401(token)
        _authorize_session(identity.session_id, session_id)
        cleared = await runtime.session_store.clear_messages(session_id)
        return {"status": "cleared", "session_id": session_id, "cleared_messages": cleared}

    @app.websocket("/ws/{session_id}")
    async def websocket_chat(websocket: WebSocket, session_id: str) -> None:
        """WebSocket chat transport for one session.

        Example:
            >>> # WS /webchat/ws/{session_id}?token=...
            >>> True
            True
        """

        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4001)
            return
        try:
            identity = verify_webchat_token(token)
        except WebChatTokenError:
            await websocket.close(code=4001)
            return
        if identity.session_id != session_id:
            await websocket.close(code=4003)
            return

        await websocket.accept()
        runtime = _runtime(app)
        state = await runtime.session_store.get_session(session_id)
        if state is None:
            state = await runtime.session_store.create_session(
                SessionState(
                    session_id=session_id,
                    tenant_id=identity.tenant_id,
                    tier=identity.tier,
                    metadata={"anonymous": identity.is_anonymous},
                )
            )
        elif state.tenant_id != identity.tenant_id:
            await websocket.send_json({"type": "error", "error": "Session ownership mismatch."})
            await websocket.close(code=4003)
            return

        restored = await runtime.session_store.get_messages(session_id, last_n=50)
        await websocket.send_json(
            {
                "type": "session_restored",
                "session": state.to_dict(),
                "messages": [row.to_dict() for row in restored],
            }
        )

        current_turn: asyncio.Task[None] | None = None
        image_processor = ImageProcessor()
        audio_processor = AudioProcessor()
        pending_images: list[ImageInput] = []
        pending_audio: list[AudioInput] = []
        try:
            while True:
                incoming = await websocket.receive()
                if incoming.get("type") == "websocket.disconnect":
                    raise WebSocketDisconnect()
                binary = incoming.get("bytes")
                if binary is not None:
                    kind, payload_bytes = _decode_binary_frame(binary)
                    if kind == "image":
                        image = image_processor.load_from_bytes(payload_bytes)
                        pending_images.append(image)
                        await websocket.send_json(
                            {
                                "type": "attachment_received",
                                "kind": "image",
                                "input_id": image.input_id,
                            }
                        )
                    else:
                        audio = audio_processor.load_from_bytes(payload_bytes)
                        pending_audio.append(audio)
                        await websocket.send_json(
                            {
                                "type": "attachment_received",
                                "kind": "audio",
                                "input_id": audio.input_id,
                            }
                        )
                    continue

                payload = json.loads(str(incoming.get("text") or "{}"))
                action = str(payload.get("type", "")).strip().lower()
                if action == "ping":
                    await websocket.send_json({"type": "pong", "ts": time.time()})
                    continue

                if action == "interrupt":
                    if current_turn and not current_turn.done():
                        current_turn.cancel()
                    else:
                        await websocket.send_json({"type": "interrupted", "active": False})
                    continue

                if action in {"approve", "deny"}:
                    request_id = str(
                        payload.get("request_id") or payload.get("action_id") or ""
                    ).strip()
                    if not request_id:
                        await websocket.send_json(
                            {"type": "approval_result", "ok": False, "error": "request_id missing"}
                        )
                        continue
                    await _handle_approval_action(
                        websocket=websocket,
                        runtime=runtime,
                        action=action,
                        request_id=request_id,
                        approver=identity.tenant_id,
                        notes=str(payload.get("notes", "")).strip() or None,
                    )
                    continue

                if action != "message":
                    await websocket.send_json(
                        {"type": "error", "error": f"Unknown action '{action}'."}
                    )
                    continue

                content = str(payload.get("content", "")).strip()
                if not content:
                    await websocket.send_json({"type": "error", "error": "content is required."})
                    continue
                if content == "__approval_context__":
                    await _send_approval_context(
                        websocket=websocket,
                        runtime=runtime,
                        action_id=str(payload.get("action_id", "")).strip(),
                    )
                    continue
                if current_turn and not current_turn.done():
                    await websocket.send_json({"type": "error", "error": "busy"})
                    continue

                translation_mode = (
                    str(payload.get("translation_mode", "off")).strip().lower() or "off"
                )
                turn_images = list(pending_images)
                turn_audio = list(pending_audio)
                pending_images.clear()
                pending_audio.clear()
                current_turn = asyncio.create_task(
                    _run_chat_turn(
                        websocket=websocket,
                        runtime=runtime,
                        session_id=session_id,
                        tenant_id=identity.tenant_id,
                        content=content,
                        translation_mode=translation_mode,
                        image_inputs=turn_images,
                        audio_inputs=turn_audio,
                    )
                )
        except WebSocketDisconnect:
            if current_turn and not current_turn.done():
                current_turn.cancel()
            return

    return app


def mount_webchat(
    parent_app: FastAPI,
    *,
    path: str = "/webchat",
    session_store: AbstractSessionStore | None = None,
    orchestrator: Orchestrator | None = None,
) -> FastAPI:
    """Mount a fresh webchat sub-app under `path`.

    Example:
        >>> main = FastAPI()
        >>> _ = mount_webchat(main)
    """

    sub_app = create_webchat_app(session_store=session_store, orchestrator=orchestrator)
    parent_app.mount(path, sub_app)
    return sub_app


def _runtime(app: FastAPI) -> WebChatRuntime:
    return app.state.runtime


def _verify_token_or_401(token: str):
    try:
        return verify_webchat_token(token)
    except WebChatTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _authorize_session(identity_session_id: str, session_id: str) -> None:
    if identity_session_id != session_id:
        raise HTTPException(status_code=403, detail="Token is not valid for this session.")


def _build_default_store() -> AbstractSessionStore:
    backend = os.getenv("ARCHON_WEBCHAT_SESSION_BACKEND", "memory")
    sqlite_path = os.getenv("ARCHON_WEBCHAT_SQLITE_PATH", DEFAULT_SQLITE_PATH)
    return create_session_store(backend=backend, sqlite_path=sqlite_path)


async def _handle_approval_action(
    *,
    websocket: WebSocket,
    runtime: WebChatRuntime,
    action: str,
    request_id: str,
    approver: str,
    notes: str | None,
) -> None:
    if runtime.orchestrator is None:
        await websocket.send_json(
            {
                "type": "approval_result",
                "ok": False,
                "request_id": request_id,
                "error": "no_orchestrator",
            }
        )
        return
    if action == "approve":
        ok = runtime.orchestrator.approval_gate.approve(request_id, approver=approver, notes=notes)
    else:
        ok = runtime.orchestrator.approval_gate.deny(
            request_id,
            reason=notes or "Denied from webchat client.",
            approver=approver,
            notes=notes,
        )
    if ok and runtime.analytics_collector is not None:
        runtime.analytics_collector.record(
            tenant_id=approver,
            event_type="approval_granted" if action == "approve" else "approval_denied",
            properties={"request_id": request_id, "approver": approver, "channel": "webchat"},
        )
    if ok and runtime.mobile_sync_store is not None:
        runtime.mobile_sync_store.record_event(
            tenant_id=approver,
            event_type="approval_resolved",
            payload={"request_id": request_id, "action": action, "channel": "webchat"},
        )
    if ok and runtime.push_notifier is not None:
        runtime.push_notifier.send_background_refresh(
            approver,
            reason="approval_resolved",
            request_id=request_id,
        )
    await websocket.send_json(
        {"type": "approval_result", "ok": ok, "request_id": request_id, "action": action}
    )


async def _run_chat_turn(
    *,
    websocket: WebSocket,
    runtime: WebChatRuntime,
    session_id: str,
    tenant_id: str,
    content: str,
    translation_mode: str = "off",
    image_inputs: list[ImageInput] | None = None,
    audio_inputs: list[AudioInput] | None = None,
) -> None:
    await runtime.session_store.append_message(
        session_id=session_id,
        message=Message(
            session_id=session_id,
            role="user",
            content=content,
            metadata={"tenant_id": tenant_id},
        ),
    )

    try:
        reply = await _assistant_reply(
            websocket=websocket,
            runtime=runtime,
            session_id=session_id,
            prompt=content,
            image_inputs=image_inputs,
            audio_inputs=audio_inputs,
            tenant_id=tenant_id,
        )
        mode = (translation_mode or "off").strip().lower()
        if mode == "off":
            for token in _tokenize(reply):
                await websocket.send_json({"type": "assistant_token", "token": token})
                await asyncio.sleep(0)
        else:
            translator = StreamingTranslator()
            tokens = _tokenize(reply)
            if mode == "auto":
                async for translated in translator.stream_detect_and_translate(tokens):
                    await websocket.send_json(
                        {
                            "type": "token",
                            "content": translated.content,
                            "original": translated.content,
                            "lang": translated.target_lang,
                        }
                    )
                    await asyncio.sleep(0)
            else:
                async for original, translated in translator.stream_translate_with_metadata(
                    tokens,
                    source_lang="en",
                    target_lang=mode,
                ):
                    await websocket.send_json(
                        {
                            "type": "token",
                            "content": translated.content,
                            "original": original,
                            "lang": translated.target_lang,
                        }
                    )
                    await asyncio.sleep(0)
        assistant = await runtime.session_store.append_message(
            session_id=session_id,
            message=Message(
                session_id=session_id,
                role="assistant",
                content=reply,
                metadata={"provider": "stub" if runtime.orchestrator is None else "orchestrator"},
            ),
        )
        await websocket.send_json({"type": "done", "message": assistant.to_dict()})
    except asyncio.CancelledError:
        await websocket.send_json({"type": "interrupted", "active": True})
        raise
    except Exception as exc:
        await websocket.send_json({"type": "error", "error": str(exc)})


async def _send_approval_context(
    *,
    websocket: WebSocket,
    runtime: WebChatRuntime,
    action_id: str,
) -> None:
    request_id = str(action_id or "").strip()
    if not request_id:
        await websocket.send_json({"type": "error", "error": "action_id is required."})
        return
    if runtime.orchestrator is None:
        await websocket.send_json({"type": "error", "error": "no_orchestrator"})
        return

    gate = runtime.orchestrator.approval_gate
    pending = [row for row in gate.pending_actions if str(row.get("action_id", "")) == request_id]
    if not pending:
        await websocket.send_json(
            {"type": "error", "error": "approval_request_not_found", "action_id": request_id}
        )
        return

    row = pending[0]
    created_at = float(row.get("created_at", time.time()))
    elapsed = max(0.0, time.time() - created_at)
    timeout_remaining = max(0.0, float(gate.default_timeout_seconds) - elapsed)
    await websocket.send_json(
        {
            "type": "approval_context",
            "action_id": request_id,
            "action": row.get("action"),
            "context": row.get("context", {}),
            "timeout_remaining_s": round(timeout_remaining, 3),
        }
    )


async def _assistant_reply(
    *,
    websocket: WebSocket,
    runtime: WebChatRuntime,
    session_id: str,
    prompt: str,
    image_inputs: list[ImageInput] | None = None,
    audio_inputs: list[AudioInput] | None = None,
    tenant_id: str = "",
) -> str:
    if runtime.orchestrator is None:
        if image_inputs or audio_inputs:
            return (
                f"ARCHON stub multimodal response: {prompt} "
                f"(images={len(image_inputs or [])}, audio={len(audio_inputs or [])})"
            )
        return f"ARCHON stub response: {prompt}"

    if image_inputs or audio_inputs:
        multimodal = MultimodalOrchestrator(runtime.orchestrator.config)
        try:
            response = await multimodal.process(
                text=prompt,
                images=list(image_inputs or []),
                audio=list(audio_inputs or []),
                session_id=session_id,
                tenant_ctx={"tenant_id": tenant_id or "webchat"},
            )
        finally:
            await multimodal.aclose()
        return response.content

    async def sink(event: dict[str, Any]) -> None:
        event_type = str(event.get("type", ""))
        if event_type == "approval_required" and runtime.analytics_collector is not None:
            runtime.analytics_collector.record(
                tenant_id=tenant_id,
                event_type="approval_requested",
                properties={
                    "request_id": str(event.get("request_id") or event.get("action_id") or ""),
                    "action": str(event.get("action") or event.get("action_type") or ""),
                    "session_id": session_id,
                },
            )
        await websocket.send_json(event)

    result = await runtime.orchestrator.execute(
        goal=prompt,
        mode="debate",
        context={"session_id": session_id, "tenant_id": tenant_id},
        event_sink=sink,
    )
    return result.final_answer


def _pending_approvals_for_tenant(
    runtime: WebChatRuntime,
    tenant_id: str,
) -> list[dict[str, Any]]:
    if runtime.orchestrator is None:
        return []
    gate = runtime.orchestrator.approval_gate
    timeout_total = float(gate.default_timeout_seconds)
    visible: list[dict[str, Any]] = []
    for row in gate.pending_actions:
        context = row.get("context", {})
        if not isinstance(context, dict):
            continue
        context_tenant = str(context.get("tenant_id", "")).strip()
        if not context_tenant or context_tenant != tenant_id:
            continue
        created_at = float(row.get("created_at", time.time()))
        elapsed = max(0.0, time.time() - created_at)
        visible.append(
            {
                "action_id": str(row.get("action_id", "")),
                "action": str(row.get("action", "")),
                "risk_level": row.get("risk_level"),
                "created_at": created_at,
                "context": dict(context),
                "timeout_remaining_s": round(max(0.0, timeout_total - elapsed), 3),
            }
        )
    return visible


def _dashboard_summary(runtime: WebChatRuntime, tenant_id: str) -> dict[str, Any]:
    collector = runtime.analytics_collector
    if collector is None:
        return {
            "sessions_24h": 0,
            "total_cost_usd_24h": 0.0,
            "approval_rate_30d": 0.0,
            "pending_approvals": 0,
            "notifications": 0,
        }
    aggregator = AnalyticsAggregator(path=collector.path)
    period_end = time.time()
    period_start_24h = period_end - 86400
    period_start_30d = period_end - (30 * 86400)
    cost_map = aggregator.cost_by_provider(tenant_id, period_start_24h, period_end)
    return {
        "sessions_24h": aggregator.total_sessions(tenant_id, period_start_24h, period_end),
        "total_cost_usd_24h": round(sum(cost_map.values()), 6),
        "approval_rate_30d": aggregator.approval_rate(tenant_id, period_start_30d, period_end),
        "pending_approvals": 0,
        "notifications": 0,
    }


def _tokenize(text: str) -> list[str]:
    chunks: list[str] = []
    parts = text.split(" ")
    for index, word in enumerate(parts):
        suffix = " " if index < len(parts) - 1 else ""
        chunks.append(word + suffix)
    return chunks


def _decode_binary_frame(frame: bytes) -> tuple[str, bytes]:
    if len(frame) < 5:
        raise ValueError("Binary frame missing header.")
    type_byte = frame[0]
    payload_length = int.from_bytes(frame[1:5], "big")
    payload = frame[5:]
    if payload_length != len(payload):
        raise ValueError("Binary frame payload length mismatch.")
    if type_byte == 0x01:
        return "image", payload
    if type_byte == 0x02:
        return "audio", payload
    raise ValueError(f"Unsupported binary frame type 0x{type_byte:02x}.")


webchat_app = create_webchat_app()
