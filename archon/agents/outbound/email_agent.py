"""Email outbound integration with approval-gated execution."""

from __future__ import annotations

import asyncio
import os
import smtplib
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage as MIMEEmailMessage
from email.utils import make_msgid
from typing import Any, Protocol

import httpx

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.core.approval_gate import ApprovalDecision, ApprovalGate
from archon.providers import ProviderRouter


@dataclass(slots=True)
class OutboundEmail:
    """Outbound email payload contract."""

    to_email: str
    subject: str
    body: str
    from_email: str | None = None
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EmailSendResult:
    """Normalized email transport response."""

    provider: str
    message_id: str
    accepted: bool
    detail: str = ""


class EmailTransport(Protocol):
    """Email transport contract used by EmailAgent."""

    async def send(self, message: OutboundEmail) -> EmailSendResult:
        """Send one outbound message and return normalized result."""


@dataclass(slots=True)
class SMTPConfig:
    """SMTP transport configuration."""

    host: str
    port: int
    from_email: str
    username: str | None = None
    password: str | None = None
    use_tls: bool = False
    use_starttls: bool = True
    timeout_seconds: float = 15.0


@dataclass(slots=True)
class SendGridConfig:
    """SendGrid transport configuration."""

    api_key: str
    from_email: str
    base_url: str = "https://api.sendgrid.com/v3"
    timeout_seconds: float = 15.0


class SMTPEmailTransport:
    """SMTP email transport implementation."""

    def __init__(self, config: SMTPConfig) -> None:
        self.config = config

    async def send(self, message: OutboundEmail) -> EmailSendResult:
        return await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: OutboundEmail) -> EmailSendResult:
        mime = MIMEEmailMessage()
        mime["Subject"] = message.subject
        mime["From"] = message.from_email or self.config.from_email
        mime["To"] = message.to_email
        mime["Message-Id"] = make_msgid(
            domain=(mime["From"].split("@")[-1] if mime["From"] else None)
        )
        if message.reply_to:
            mime["Reply-To"] = message.reply_to
        mime.set_content(message.body)

        if self.config.use_tls:
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                self.config.host,
                self.config.port,
                timeout=self.config.timeout_seconds,
            )
        else:
            server = smtplib.SMTP(
                self.config.host,
                self.config.port,
                timeout=self.config.timeout_seconds,
            )
        try:
            if self.config.use_starttls and not self.config.use_tls:
                server.starttls()
            if self.config.username and self.config.password:
                server.login(self.config.username, self.config.password)
            server.send_message(mime)
        finally:
            server.quit()

        return EmailSendResult(
            provider="smtp",
            message_id=str(mime["Message-Id"] or f"smtp-{uuid.uuid4().hex[:12]}"),
            accepted=True,
            detail="SMTP message accepted by local client.",
        )


class SendGridEmailTransport:
    """SendGrid HTTP API transport implementation."""

    def __init__(self, config: SendGridConfig) -> None:
        self.config = config

    async def send(self, message: OutboundEmail) -> EmailSendResult:
        payload = {
            "personalizations": [{"to": [{"email": message.to_email}]}],
            "from": {"email": message.from_email or self.config.from_email},
            "subject": message.subject,
            "content": [{"type": "text/plain", "value": message.body}],
        }
        if message.reply_to:
            payload["reply_to"] = {"email": message.reply_to}

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post(
                f"{self.config.base_url.rstrip('/')}/mail/send",
                json=payload,
                headers=headers,
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"SendGrid send failed with HTTP {response.status_code}: {response.text}"
            )

        message_id = response.headers.get("x-message-id") or f"sendgrid-{uuid.uuid4().hex[:12]}"
        return EmailSendResult(
            provider="sendgrid",
            message_id=message_id,
            accepted=True,
            detail="SendGrid accepted message.",
        )


class NullEmailTransport:
    """No-op transport that fails fast when email is not configured."""

    async def send(self, message: OutboundEmail) -> EmailSendResult:
        del message
        raise RuntimeError(
            "Email transport not configured. Set ARCHON_EMAIL_PROVIDER and required credentials."
        )


class EmailAgent(BaseAgent):
    """Outbound email agent guarded by human approval.

    Example:
        >>> result = await email_agent.send_email(
        ...     task_id="task-1",
        ...     to_email="lead@example.com",
        ...     subject="Quick follow-up",
        ...     body="Can we schedule a 15-minute demo?",
        ... )
        >>> result.agent
        'EmailAgent'
    """

    role = "fast"

    def __init__(
        self,
        router: ProviderRouter,
        approval_gate: ApprovalGate,
        transport: EmailTransport | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(router, name=name or "EmailAgent")
        self.approval_gate = approval_gate
        self.transport = transport or build_email_transport_from_env()

    async def send_email(
        self,
        *,
        task_id: str,
        to_email: str,
        subject: str,
        body: str,
        from_email: str | None = None,
        reply_to: str | None = None,
        metadata: dict[str, Any] | None = None,
        event_sink=None,
    ) -> AgentResult:
        """Send one approval-gated outbound email."""

        message = OutboundEmail(
            to_email=to_email,
            subject=subject,
            body=body,
            from_email=from_email,
            reply_to=reply_to,
            metadata=metadata or {},
        )

        approval_payload = {
            "task_id": task_id,
            "channel": "email",
            "to_email": to_email,
            "subject": subject,
            "metadata": message.metadata,
        }
        decision: ApprovalDecision = await self.approval_gate.guard(
            action_type="outbound_email",
            payload=approval_payload,
            event_sink=event_sink,
        )

        send_result = await self.transport.send(message)
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=f"Email sent to {to_email} with provider {send_result.provider}.",
            confidence=95,
            metadata={
                "task_id": task_id,
                "channel": "email",
                "provider": send_result.provider,
                "message_id": send_result.message_id,
                "accepted": send_result.accepted,
                "detail": send_result.detail,
                "approval": decision.to_event_payload(),
                "metadata": message.metadata,
            },
        )

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Execute default email action from context payload."""

        del goal
        return await self.send_email(
            task_id=task_id,
            to_email=str(context["to_email"]),
            subject=str(context["subject"]),
            body=str(context["body"]),
            from_email=context.get("from_email"),
            reply_to=context.get("reply_to"),
            metadata=context.get("metadata") if isinstance(context.get("metadata"), dict) else None,
            event_sink=context.get("event_sink"),
        )


def build_email_transport_from_env() -> EmailTransport:
    """Build configured email transport from environment variables."""

    provider = os.getenv("ARCHON_EMAIL_PROVIDER", "").strip().lower()
    if provider == "smtp":
        host = os.getenv("ARCHON_SMTP_HOST", "").strip()
        port = int(os.getenv("ARCHON_SMTP_PORT", "587"))
        from_email = os.getenv("ARCHON_EMAIL_FROM", "").strip()
        if not host or not from_email:
            return NullEmailTransport()
        return SMTPEmailTransport(
            SMTPConfig(
                host=host,
                port=port,
                from_email=from_email,
                username=os.getenv("ARCHON_SMTP_USERNAME") or None,
                password=os.getenv("ARCHON_SMTP_PASSWORD") or None,
                use_tls=os.getenv("ARCHON_SMTP_USE_TLS", "false").lower() == "true",
                use_starttls=os.getenv("ARCHON_SMTP_USE_STARTTLS", "true").lower() != "false",
            )
        )

    if provider == "sendgrid":
        api_key = os.getenv("SENDGRID_API_KEY", "").strip()
        from_email = os.getenv("ARCHON_EMAIL_FROM", "").strip()
        if not api_key or not from_email:
            return NullEmailTransport()
        return SendGridEmailTransport(
            SendGridConfig(
                api_key=api_key,
                from_email=from_email,
                base_url=os.getenv("ARCHON_SENDGRID_BASE_URL", "https://api.sendgrid.com/v3"),
            )
        )

    return NullEmailTransport()
