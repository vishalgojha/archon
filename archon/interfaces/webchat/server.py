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
from archon.multimodal import AudioInput, AudioProcessor, ImageInput, ImageProcessor, MultimodalOrchestrator
from archon.vernacular.streaming import StreamingTranslator

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


class CreateTokenRequest(BaseModel):
    """Token creation payload."""

    session_id: str | None = None


class UpgradeTokenRequest(BaseModel):
    """Anonymous-to-identified upgrade payload."""

    token: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    tier: str = Field(min_length=1)


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

    app = FastAPI(title="ARCHON WebChat", version="0.1.0")
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
                            {"type": "attachment_received", "kind": "image", "input_id": image.input_id}
                        )
                    else:
                        audio = audio_processor.load_from_bytes(payload_bytes)
                        pending_audio.append(audio)
                        await websocket.send_json(
                            {"type": "attachment_received", "kind": "audio", "input_id": audio.input_id}
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
        if event_type in {"approval_required", "approval_resolved", "growth_agent_completed"}:
            await websocket.send_json(event)

    result = await runtime.orchestrator.execute(
        goal=prompt,
        mode="debate",
        context={"session_id": session_id},
        event_sink=sink,
    )
    return result.final_answer


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
