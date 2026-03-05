"""Approval-gated outreach email agent with single and bulk send support."""

from __future__ import annotations

import asyncio
from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.outreach.email_backends import (
    EmailBackend,
    EmailPayload,
    SMTPBackend,
    SendGridBackend,
    SendResult,
    UnsubscribeStore,
    build_email_backend_from_env,
    build_unsubscribe_footer,
    personalize,
)
from archon.core.approval_gate import ApprovalDeniedError, ApprovalGate
from archon.providers import ProviderRouter


class EmailAgent(BaseAgent):
    """Approval-gated outreach email agent."""

    role = "fast"

    def __init__(
        self,
        router: ProviderRouter,
        approval_gate: ApprovalGate,
        *,
        backend: EmailBackend | None = None,
        unsubscribe_store: UnsubscribeStore | None = None,
        unsubscribe_url: str = "https://example.invalid/unsubscribe",
        name: str | None = None,
    ) -> None:
        """Create agent. Example: `EmailAgent(router, gate)`."""

        super().__init__(router, name=name or "EmailAgent")
        self.approval_gate = approval_gate
        self.backend = backend or build_email_backend_from_env()
        self.unsubscribe_store = unsubscribe_store or UnsubscribeStore()
        self.unsubscribe_url = unsubscribe_url
        self.send_log: list[dict[str, Any]] = []

    async def send(
        self,
        to: str,
        subject: str,
        body_text: str,
        *,
        body_html: str | None = None,
        reply_to: str | None = None,
        cc: list[str] | None = None,
        context: dict[str, Any] | None = None,
        add_unsubscribe_footer: bool = True,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> SendResult:
        """Send one email. Example: `await agent.send('a@x','Hi','Body')`."""

        address = to.strip().lower()
        if not address:
            result = SendResult(to, "failed", "none", error="Recipient email is empty.")
            self._audit(result, subject)
            return result
        if self.unsubscribe_store.is_unsubscribed(address):
            result = SendResult(address, "blocked:unsubscribed", "none")
            self._audit(result, subject)
            return result
        merged = context or {}
        rendered_subject = personalize(subject, merged)
        rendered_text = personalize(body_text, merged)
        rendered_html = personalize(body_html, merged) if body_html else None
        if add_unsubscribe_footer:
            rendered_text = rendered_text + build_unsubscribe_footer(address, self.unsubscribe_url)
        payload = EmailPayload(
            to=address,
            subject=rendered_subject,
            body_text=rendered_text,
            body_html=rendered_html,
            reply_to=reply_to,
            cc=list(cc or []),
        )
        preview = rendered_text[:200]
        try:
            await self.approval_gate.guard(
                action_type="email_send",
                payload={"to": address, "subject": rendered_subject, "body_preview": preview},
                event_sink=event_sink,
                timeout_seconds=timeout_seconds,
            )
        except ApprovalDeniedError as exc:
            result = SendResult(address, f"denied:{exc.reason}", "none", error=str(exc))
            self._audit(result, rendered_subject)
            return result
        result = await self.backend.send(payload)
        self._audit(result, rendered_subject)
        return result

    async def send_bulk(
        self,
        recipients: list[dict[str, Any]],
        subject: str,
        body_text: str,
        *,
        body_html: str | None = None,
        delay_between_s: float = 0.5,
        add_unsubscribe_footer: bool = True,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> list[SendResult]:
        """Send personalized emails to many recipients. Example: `await agent.send_bulk([...],s,b)`."""

        results: list[SendResult] = []
        for index, row in enumerate(recipients):
            email = str(row.get("email", "")).strip()
            if not email:
                failed = SendResult("", "failed", "none", error="Recipient email is empty.")
                self._audit(failed, subject)
                results.append(failed)
            else:
                results.append(
                    await self.send(
                        to=email,
                        subject=subject,
                        body_text=body_text,
                        body_html=body_html,
                        context=row,
                        add_unsubscribe_footer=add_unsubscribe_footer,
                        event_sink=event_sink,
                        timeout_seconds=timeout_seconds,
                    )
                )
            if index < len(recipients) - 1 and delay_between_s > 0:
                await asyncio.sleep(delay_between_s)
        return results

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run default action wrapper. Example: `await agent.run('x', {...}, 't1')`."""

        del goal, task_id
        result = await self.send(
            to=str(context.get("to", "")),
            subject=str(context.get("subject", "")),
            body_text=str(context.get("body_text", "")),
            body_html=context.get("body_html"),
            reply_to=context.get("reply_to"),
            cc=context.get("cc") if isinstance(context.get("cc"), list) else None,
            context=context.get("personalization")
            if isinstance(context.get("personalization"), dict)
            else None,
        )
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=f"Email send status: {result.status}",
            confidence=95 if result.ok else 20,
            metadata={"send_result": result.__dict__},
        )

    def _audit(self, result: SendResult, subject: str) -> None:
        self.send_log.append(
            {
                "to": result.to,
                "subject": subject,
                "status": result.status,
                "provider": result.provider,
                "message_id": result.message_id,
                "error": result.error,
            }
        )


__all__ = [
    "EmailAgent",
    "EmailPayload",
    "EmailBackend",
    "SendResult",
    "UnsubscribeStore",
    "SMTPBackend",
    "SendGridBackend",
    "personalize",
    "build_unsubscribe_footer",
]
