"""Approval-gated voice outreach agent with Twilio + Whisper transcription."""

from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.outreach.voice_adapter import VernacularAdapter, normalize_language_code
from archon.core.approval_gate import ApprovalDeniedError, ApprovalGate
from archon.providers import ProviderRouter


@dataclass(slots=True, frozen=True)
class CallResult:
    """Outbound call initiation result.

    Example: `CallResult("CA123", "queued").ok`.
    """

    call_sid: str
    status: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Success flag. Example: `CallResult("CA1", "queued").ok`."""

        return self.status in {"queued", "ringing", "in-progress", "completed"}


@dataclass(slots=True, frozen=True)
class TranscriptionResult:
    """Voice transcription output.

    Example: `TranscriptionResult("CA1", "Hello", 0.9, 2.0, "en")`.
    """

    call_sid: str
    transcript: str
    confidence: float
    duration_s: float
    language: str


class VoiceAgent(BaseAgent):
    """Twilio voice caller with approval gate and recording transcription."""

    role = "fast"

    def __init__(
        self,
        router: ProviderRouter,
        approval_gate: ApprovalGate,
        *,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
        openai_api_key: str | None = None,
        vernacular_adapter: VernacularAdapter | None = None,
        name: str | None = None,
    ) -> None:
        """Create voice agent. Example: `VoiceAgent(router, gate)`."""

        super().__init__(router, name=name or "VoiceAgent")
        self.approval_gate = approval_gate
        self.account_sid = (account_sid or os.getenv("TWILIO_ACCOUNT_SID", "")).strip()
        self.auth_token = (auth_token or os.getenv("TWILIO_AUTH_TOKEN", "")).strip()
        self.from_number = (from_number or os.getenv("TWILIO_VOICE_FROM", "")).strip()
        self.openai_api_key = (openai_api_key or os.getenv("OPENAI_API_KEY", "")).strip()
        self.vernacular = vernacular_adapter or VernacularAdapter()
        self.send_log: list[dict[str, Any]] = []

    async def initiate_call(
        self,
        to: str,
        twiml_or_script: str,
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> CallResult:
        """Initiate one outbound voice call.

        Input can be raw TwiML or plain script text.
        Example: `await agent.initiate_call("+1", "Hello there")`.
        """

        target = str(to).strip()
        twiml = self._ensure_twiml(twiml_or_script)
        if not target:
            result = CallResult("", "failed", error="Recipient is empty.")
            self._audit("call", target, result.status, result.call_sid, result.error)
            return result
        denied = await self._guard_send(target, twiml, event_sink=event_sink, timeout_seconds=timeout_seconds)
        if denied is not None:
            self._audit("call", target, denied.status, denied.call_sid, denied.error)
            return denied
        if not self.account_sid or not self.auth_token or not self.from_number:
            result = CallResult("", "failed", error="Twilio config missing account_sid/auth_token/from_number.")
            self._audit("call", target, result.status, result.call_sid, result.error)
            return result

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Calls.json"
        payload = {"To": target, "From": self.from_number, "Twiml": twiml}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, data=payload, auth=(self.account_sid, self.auth_token))
            if response.status_code in {200, 201}:
                data = _safe_json(response)
                result = CallResult(
                    call_sid=str(data.get("sid", "")),
                    status=str(data.get("status", "") or "queued"),
                )
                self._audit("call", target, result.status, result.call_sid, None)
                return result
            result = CallResult("", "failed", error=f"HTTP {response.status_code}: {response.text}")
            self._audit("call", target, result.status, result.call_sid, result.error)
            return result
        except Exception as exc:  # pragma: no cover - defensive wrapper
            result = CallResult("", "failed", error=str(exc))
            self._audit("call", target, result.status, result.call_sid, result.error)
            return result

    async def handle_recording_webhook(self, payload: dict[str, Any]) -> TranscriptionResult:
        """Download recording and transcribe via Whisper API.

        Example: `await agent.handle_recording_webhook({"CallSid":"CA1","RecordingUrl":"..."})`.
        """

        call_sid = str(payload.get("CallSid", "")).strip()
        recording_url = str(payload.get("RecordingUrl", "")).strip()
        duration = _parse_float(payload.get("RecordingDuration"), default=0.0)
        if not recording_url or not self.openai_api_key:
            return TranscriptionResult(call_sid, "", 0.0, duration, "und")

        download_url = _normalize_recording_url(recording_url)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                recording_response = await client.get(
                    download_url,
                    auth=(self.account_sid, self.auth_token) if self.account_sid and self.auth_token else None,
                )
                recording_response.raise_for_status()
                audio_bytes = recording_response.content

                files = {"file": ("recording.mp3", audio_bytes, "audio/mpeg")}
                form = {"model": "whisper-1"}
                whisper_response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.openai_api_key}"},
                    data=form,
                    files=files,
                )
                whisper_response.raise_for_status()
                data = _safe_json(whisper_response)
            transcript = str(data.get("text", "")).strip()
            language = normalize_language_code(str(data.get("language", "")).strip() or "und")
            confidence = _parse_float(data.get("confidence"), default=(0.9 if transcript else 0.0))
            duration_s = _parse_float(data.get("duration"), default=duration)
            self._audit("transcription", call_sid, "ok", call_sid, None)
            return TranscriptionResult(call_sid, transcript, confidence, duration_s, language)
        except Exception as exc:  # pragma: no cover - defensive wrapper
            self._audit("transcription", call_sid, "failed", call_sid, str(exc))
            return TranscriptionResult(call_sid, "", 0.0, duration, "und")

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run one default call initiation action.

        Example: `await agent.run("call", {"to":"+1","script":"Hi"}, "t1")`.
        """

        del goal, task_id
        result = await self.initiate_call(
            str(context.get("to", "")),
            str(context.get("twiml_or_script") or context.get("script") or ""),
            event_sink=context.get("event_sink"),
        )
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=f"Voice call status: {result.status}",
            confidence=95 if result.ok else 20,
            metadata={"call_result": result.__dict__},
        )

    async def _guard_send(
        self,
        to: str,
        preview: str,
        *,
        event_sink,
        timeout_seconds: float | None,
    ) -> CallResult | None:
        try:
            await self.approval_gate.guard(
                action_type="send_message",
                payload={"channel": "voice", "to": to, "twiml_preview": preview[:200]},
                event_sink=event_sink,
                timeout_seconds=timeout_seconds,
            )
            return None
        except ApprovalDeniedError as exc:
            return CallResult("", f"denied:{exc.reason}", error=str(exc))

    def _audit(self, action: str, to: str, status: str, call_sid: str, error: str | None) -> None:
        self.send_log.append(
            {
                "action": action,
                "to": to,
                "status": status,
                "provider": "twilio",
                "call_sid": call_sid,
                "error": error,
                "timestamp": time.time(),
            }
        )

    @staticmethod
    def _ensure_twiml(twiml_or_script: str) -> str:
        raw = str(twiml_or_script).strip()
        if raw.lower().startswith("<response"):
            return raw
        escaped = html.escape(raw or "Hello from ARCHON.")
        return f"<Response><Say>{escaped}</Say></Response>"


def _normalize_recording_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.endswith(".mp3") or path.endswith(".wav"):
        return url
    return f"{url}.mp3"


def _parse_float(raw: Any, *, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


__all__ = ["CallResult", "TranscriptionResult", "VernacularAdapter", "VoiceAgent"]
