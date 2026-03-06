"""Approval-gated WhatsApp outreach agent and inbound webhook parser."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.outreach.email_agent import UnsubscribeStore, personalize
from archon.agents.outreach.whatsapp_backends import (
    MetaBackend,
    SendResult,
    TemplateMessage,
    TwilioBackend,
    WhatsAppBackend,
    build_whatsapp_backend_from_env,
    strip_whatsapp_prefix,
)
from archon.core.approval_gate import ApprovalDeniedError, ApprovalGate
from archon.providers import ProviderRouter


@dataclass(slots=True, frozen=True)
class InboundMessage:
    """Normalized inbound WhatsApp message payload.

    Example: `InboundMessage("+1555", "Hi", 1.0, "mid")`.
    """

    from_number: str
    body: str
    timestamp: float
    message_id: str


class WhatsAppAgent(BaseAgent):
    """WhatsApp outreach agent with mandatory send-message approvals."""

    role = "fast"

    def __init__(
        self,
        router: ProviderRouter,
        approval_gate: ApprovalGate,
        *,
        backend: WhatsAppBackend | None = None,
        unsubscribe_store: UnsubscribeStore | None = None,
        name: str | None = None,
    ) -> None:
        """Create an approval-gated WhatsApp agent.

        Example: `WhatsAppAgent(router, gate)`.
        """

        super().__init__(router, name=name or "WhatsAppAgent")
        self.approval_gate = approval_gate
        self.backend = backend or build_whatsapp_backend_from_env()
        self.unsubscribe_store = unsubscribe_store or UnsubscribeStore()
        self.send_log: list[dict[str, Any]] = []

    async def send_text(
        self,
        to: str,
        body: str,
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> SendResult:
        """Send a plain WhatsApp message after approval and unsubscribe checks.

        Example: `await agent.send_text("+1555", "Hi")`.
        """

        target = strip_whatsapp_prefix(to)
        if not target:
            result = SendResult(target, "failed", "none", error="Recipient is empty.")
            self._audit("text", result, body)
            return result
        if self.unsubscribe_store.is_unsubscribed(target):
            result = SendResult(target, "blocked:unsubscribed", "none")
            self._audit("text", result, body)
            return result

        denied = await self._guard_send(
            target, body, event_sink=event_sink, timeout_seconds=timeout_seconds
        )
        if denied is not None:
            self._audit("text", denied, body)
            return denied

        result = await self.backend.send_text(target, body)
        self._audit("text", result, body)
        return result

    async def send_template(
        self,
        to: str,
        template: TemplateMessage,
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> SendResult:
        """Send a WhatsApp template message after approval and unsubscribe checks.

        Example: `await agent.send_template("+1555", TemplateMessage(...))`.
        """

        target = strip_whatsapp_prefix(to)
        if not target:
            result = SendResult(target, "failed", "none", error="Recipient is empty.")
            self._audit("template", result, template.template_name)
            return result
        if self.unsubscribe_store.is_unsubscribed(target):
            result = SendResult(target, "blocked:unsubscribed", "none")
            self._audit("template", result, template.template_name)
            return result

        denied = await self._guard_send(
            target,
            f"template:{template.template_name}",
            event_sink=event_sink,
            timeout_seconds=timeout_seconds,
        )
        if denied is not None:
            self._audit("template", denied, template.template_name)
            return denied

        result = await self.backend.send_template(target, template)
        self._audit("template", result, template.template_name)
        return result

    async def send_bulk(
        self,
        recipients: list[dict[str, Any] | str],
        body_template: str,
        personalization_key: str = "name",
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> list[SendResult]:
        """Send a personalized text template to many recipients one-by-one.

        Example: `await agent.send_bulk([{"to":"+1555","name":"A"}], "Hi {{name}}")`.
        """

        results: list[SendResult] = []
        for row in recipients:
            if isinstance(row, dict):
                to = str(row.get("to") or row.get("phone") or row.get("number") or "").strip()
                context = dict(row)
            else:
                to = str(row).strip()
                context = {personalization_key: to}
            body = personalize(body_template, context)
            results.append(
                await self.send_text(
                    to, body, event_sink=event_sink, timeout_seconds=timeout_seconds
                )
            )
            await asyncio.sleep(0)
        return results

    def handle_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        """Parse inbound Twilio or Meta webhook payload into a single message object.

        Example: `agent.handle_inbound({"From": "...", "Body": "..."})`.
        """

        if not isinstance(payload, dict):
            return None
        if "From" in payload and "Body" in payload:
            return InboundMessage(
                from_number=strip_whatsapp_prefix(str(payload.get("From", ""))),
                body=str(payload.get("Body", "")),
                timestamp=_parse_timestamp(payload.get("Timestamp") or payload.get("DateCreated")),
                message_id=str(payload.get("MessageSid") or payload.get("SmsMessageSid") or ""),
            )
        try:
            messages = payload["entry"][0]["changes"][0]["value"]["messages"]
            if not isinstance(messages, list) or not messages:
                return None
            message = messages[0]
            body = str(((message.get("text") or {}).get("body")) or "")
            return InboundMessage(
                from_number=str(message.get("from", "")),
                body=body,
                timestamp=_parse_timestamp(message.get("timestamp")),
                message_id=str(message.get("id", "")),
            )
        except Exception:
            return None

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run default action wrapper by dispatching `send_text`.

        Example: `await agent.run("send", {"to":"+1555","body":"Hi"}, "task-1")`.
        """

        del goal, task_id
        result = await self.send_text(
            to=str(context.get("to", "")),
            body=str(context.get("body", "")),
            event_sink=context.get("event_sink"),
        )
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=f"WhatsApp send status: {result.status}",
            confidence=95 if result.ok else 20,
            metadata={"send_result": result.__dict__},
        )

    async def _guard_send(
        self,
        to: str,
        preview: str,
        *,
        event_sink,
        timeout_seconds: float | None,
    ) -> SendResult | None:
        try:
            await self.approval_gate.guard(
                action_type="send_message",
                payload={"channel": "whatsapp", "to": to, "body_preview": preview[:200]},
                event_sink=event_sink,
                timeout_seconds=timeout_seconds,
            )
            return None
        except ApprovalDeniedError as exc:
            return SendResult(to, f"denied:{exc.reason}", "none", error=str(exc))

    def _audit(self, message_type: str, result: SendResult, preview: str) -> None:
        self.send_log.append(
            {
                "to": result.to,
                "type": message_type,
                "preview": preview[:120],
                "status": result.status,
                "provider": result.provider,
                "provider_message_id": result.provider_message_id,
                "error": result.error,
            }
        )


def _parse_timestamp(value: Any) -> float:
    """Convert webhook timestamp fields to unix seconds.

    Example: `_parse_timestamp("1700000000")`.
    """

    if value is None:
        return time.time()
    try:
        return float(value)
    except (TypeError, ValueError):
        return time.time()


__all__ = [
    "InboundMessage",
    "MetaBackend",
    "SendResult",
    "TemplateMessage",
    "TwilioBackend",
    "WhatsAppAgent",
]
