"""Approval-gated SMS outreach agent using Twilio Programmable SMS."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.outreach.email_agent import UnsubscribeStore, personalize
from archon.core.approval_gate import ApprovalDeniedError, ApprovalGate
from archon.providers import ProviderRouter

_STOP_KEYWORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}


@dataclass(slots=True, frozen=True)
class SendResult:
    """SMS send result.

    Example: `SendResult("+1", "sent", "twilio").ok`.
    """

    to: str
    status: str
    provider: str
    provider_message_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Success flag. Example: `SendResult("+1", "sent", "twilio").ok`."""

        return self.status == "sent"


@dataclass(slots=True, frozen=True)
class InboundSMS:
    """Normalized inbound SMS event.

    Example: `InboundSMS("+1", "Hello", 1.0)`.
    """

    from_number: str
    body: str
    timestamp: float


class SMSAgent(BaseAgent):
    """Twilio SMS sender with approval gate and unsubscribe enforcement."""

    role = "fast"

    def __init__(
        self,
        router: ProviderRouter,
        approval_gate: ApprovalGate,
        *,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
        unsubscribe_store: UnsubscribeStore | None = None,
        name: str | None = None,
    ) -> None:
        """Create SMS agent. Example: `SMSAgent(router, gate)`."""

        super().__init__(router, name=name or "SMSAgent")
        self.approval_gate = approval_gate
        self.account_sid = (account_sid or os.getenv("TWILIO_ACCOUNT_SID", "")).strip()
        self.auth_token = (auth_token or os.getenv("TWILIO_AUTH_TOKEN", "")).strip()
        self.from_number = (from_number or os.getenv("TWILIO_SMS_FROM", "")).strip()
        self.unsubscribe_store = unsubscribe_store or UnsubscribeStore()
        self.send_log: list[dict[str, Any]] = []

    async def send(
        self,
        to: str,
        body: str,
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> SendResult:
        """Send one SMS message.

        Example: `await agent.send("+15550001111", "Hello")`.
        """

        target = str(to).strip()
        text = str(body)
        if not target:
            result = SendResult(target, "failed", "none", error="Recipient is empty.")
            self._audit(result, text)
            return result
        if self.unsubscribe_store.is_unsubscribed(target):
            result = SendResult(target, "blocked:unsubscribed", "none")
            self._audit(result, text)
            return result
        if len(text) > 1600:
            result = SendResult(
                target,
                "failed",
                "none",
                error="SMS body exceeds hard cap of 1600 characters.",
                metadata={"max_length": 1600},
            )
            self._audit(result, text)
            return result

        metadata: dict[str, Any] = {}
        if len(text) > 160:
            metadata["warning"] = "Body exceeds 160 chars; carrier may send as segmented SMS."

        denied = await self._guard_send(
            target, text, event_sink=event_sink, timeout_seconds=timeout_seconds
        )
        if denied is not None:
            denied.metadata.update(metadata)
            self._audit(denied, text)
            return denied

        if not self.account_sid or not self.auth_token or not self.from_number:
            result = SendResult(
                target,
                "failed",
                "twilio",
                error="Twilio config missing account_sid/auth_token/from_number.",
                metadata=metadata,
            )
            self._audit(result, text)
            return result

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        payload = {"To": target, "From": self.from_number, "Body": text}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    url, data=payload, auth=(self.account_sid, self.auth_token)
                )
            if response.status_code in {200, 201}:
                data = _safe_json(response)
                result = SendResult(
                    target,
                    "sent",
                    "twilio",
                    provider_message_id=str(data.get("sid", "")) or None,
                    metadata=metadata,
                )
                self._audit(result, text)
                return result
            result = SendResult(
                target,
                "failed",
                "twilio",
                error=f"HTTP {response.status_code}: {response.text}",
                metadata=metadata,
            )
            self._audit(result, text)
            return result
        except Exception as exc:  # pragma: no cover - defensive wrapper
            result = SendResult(target, "failed", "twilio", error=str(exc), metadata=metadata)
            self._audit(result, text)
            return result

    async def send_bulk(
        self,
        recipients: list[dict[str, Any] | str],
        body_template: str,
        *,
        personalization_key: str = "name",
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> list[SendResult]:
        """Send personalized SMS in sequence.

        Example: `await agent.send_bulk([{"to":"+1","name":"A"}], "Hi {{name}}")`.
        """

        results: list[SendResult] = []
        for row in recipients:
            if isinstance(row, dict):
                target = str(row.get("to") or row.get("phone") or row.get("number") or "").strip()
                context = dict(row)
            else:
                target = str(row).strip()
                context = {personalization_key: target}
            body = personalize(body_template, context)
            results.append(
                await self.send(
                    target,
                    body,
                    event_sink=event_sink,
                    timeout_seconds=timeout_seconds,
                )
            )
        return results

    def handle_inbound(self, payload: dict[str, Any]) -> InboundSMS | None:
        """Parse inbound Twilio webhook payload.

        STOP-like keywords are auto-added to `unsubscribe_store`.
        Example: `agent.handle_inbound({"From":"+1","Body":"STOP"})`.
        """

        if not isinstance(payload, dict):
            return None
        from_number = str(payload.get("From", "")).strip()
        body = str(payload.get("Body", "")).strip()
        if not from_number:
            return None
        if body.upper().strip() in _STOP_KEYWORDS:
            self.unsubscribe_store.add(from_number)
        return InboundSMS(
            from_number=from_number,
            body=body,
            timestamp=_parse_timestamp(payload.get("Timestamp") or payload.get("DateCreated")),
        )

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run one default SMS action.

        Example: `await agent.run("send", {"to":"+1","body":"Hi"}, "t1")`.
        """

        del goal, task_id
        result = await self.send(
            str(context.get("to", "")),
            str(context.get("body", "")),
            event_sink=context.get("event_sink"),
        )
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=f"SMS send status: {result.status}",
            confidence=95 if result.ok else 20,
            metadata={"send_result": result.__dict__},
        )

    async def _guard_send(
        self,
        to: str,
        body: str,
        *,
        event_sink,
        timeout_seconds: float | None,
    ) -> SendResult | None:
        try:
            await self.approval_gate.guard(
                action_type="send_message",
                payload={"channel": "sms", "to": to, "body_preview": body[:200]},
                event_sink=event_sink,
                timeout_seconds=timeout_seconds,
            )
            return None
        except ApprovalDeniedError as exc:
            return SendResult(to, f"denied:{exc.reason}", "none", error=str(exc))

    def _audit(self, result: SendResult, body: str) -> None:
        self.send_log.append(
            {
                "to": result.to,
                "preview": body[:120],
                "status": result.status,
                "provider": result.provider,
                "provider_message_id": result.provider_message_id,
                "error": result.error,
                "metadata": dict(result.metadata),
            }
        )


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_timestamp(raw: Any) -> float:
    if raw is None:
        return time.time()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return time.time()


__all__ = ["InboundSMS", "SMSAgent", "SendResult", "UnsubscribeStore"]
