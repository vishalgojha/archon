"""Email backends and helper utilities for outreach sending."""

from __future__ import annotations

import asyncio
import importlib
import os
import re
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any, Protocol
from urllib.parse import quote

import httpx

_TOKEN_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


@dataclass(slots=True)
class EmailPayload:
    """Structured outbound email payload."""

    to: str
    subject: str
    body_text: str
    body_html: str | None = None
    from_address: str | None = None
    reply_to: str | None = None
    cc: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SendResult:
    """Backend send result. Example: `SendResult('a@x','sent','smtp').ok`."""

    to: str
    status: str
    provider: str
    message_id: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Success flag. Example: `SendResult('a','sent','smtp').ok`."""

        return self.status == "sent"


class EmailBackend(Protocol):
    """Transport contract for one email send."""

    async def send(self, payload: EmailPayload) -> SendResult:
        """Send one email payload. Example: `await backend.send(payload)`."""


def personalize(template: str, context: dict[str, Any] | None) -> str:
    """Replace `{{token}}` placeholders. Example: `personalize('Hi {{name}}',{'name':'A'})`."""

    if not template:
        return ""
    mapping = context or {}
    return _TOKEN_RE.sub(
        lambda m: str(mapping[m.group(1)]) if m.group(1) in mapping else m.group(0),
        template,
    )


def build_unsubscribe_footer(email: str, url: str) -> str:
    """Build footer text. Example: `build_unsubscribe_footer('a@x','https://u')`."""

    base = (url or "https://example.invalid/unsubscribe").strip()
    sep = "&" if "?" in base else "?"
    return f"\n\n---\nUnsubscribe: {base}{sep}email={quote(email)}"


class UnsubscribeStore:
    """Case-insensitive in-memory unsubscribe registry."""

    def __init__(self) -> None:
        """Create store. Example: `store = UnsubscribeStore(); store.count`."""

        self._rows: set[str] = set()

    def add(self, email: str) -> None:
        """Add one email. Example: `store.add('a@x.com')`."""

        key = email.strip().lower()
        if key:
            self._rows.add(key)

    def remove(self, email: str) -> None:
        """Remove one email. Example: `store.remove('a@x.com')`."""

        self._rows.discard(email.strip().lower())

    def is_unsubscribed(self, email: str) -> bool:
        """Check membership. Example: `store.is_unsubscribed('a@x.com')`."""

        return email.strip().lower() in self._rows

    def bulk_add(self, emails: list[str]) -> None:
        """Add many emails. Example: `store.bulk_add(['a@x.com','b@x.com'])`."""

        for email in emails:
            self.add(email)

    @property
    def count(self) -> int:
        """Total unsubscribed count. Example: `store.count`."""

        return len(self._rows)


class SMTPBackend:
    """SMTP backend using `aiosmtplib` when available."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str = "",
        password: str = "",
        use_tls: bool = False,
        from_address: str = "",
    ) -> None:
        """Build SMTP backend. Example: `SMTPBackend('smtp',587,from_address='n@x')`."""

        self.host = host.strip()
        self.port = int(port)
        self.user = user
        self.password = password
        self.use_tls = bool(use_tls)
        self.from_address = from_address.strip()

    @classmethod
    def from_env(cls) -> "SMTPBackend":
        """Load config from env. Example: `SMTPBackend.from_env().port`."""

        return cls(
            host=os.getenv("SMTP_HOST", ""),
            port=int(os.getenv("SMTP_PORT", "587")),
            user=os.getenv("SMTP_USER", ""),
            password=os.getenv("SMTP_PASSWORD", ""),
            use_tls=_parse_bool(os.getenv("SMTP_USE_TLS", "false")),
            from_address=os.getenv("SMTP_FROM_ADDRESS", ""),
        )

    async def send(self, payload: EmailPayload) -> SendResult:
        """Send email payload. Example: `await SMTPBackend.from_env().send(payload)`."""

        if not self.host or not self.from_address:
            return SendResult(payload.to, "failed", "smtp", error="SMTP config missing host/from.")
        message = self._build_message(payload)
        recipients = [payload.to, *[item for item in payload.cc if item.strip()]]
        try:
            aiosmtplib = self._load_aiosmtplib()
            if aiosmtplib is not None:
                await aiosmtplib.send(
                    message,
                    hostname=self.host,
                    port=self.port,
                    username=self.user or None,
                    password=self.password or None,
                    use_tls=self.use_tls,
                    start_tls=not self.use_tls,
                )
            else:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._send_with_smtplib, message, recipients)
            return SendResult(payload.to, "sent", "smtp", message_id=str(message["Message-ID"]))
        except Exception as exc:  # pragma: no cover - defensive transport wrapper
            return SendResult(payload.to, "failed", "smtp", error=str(exc))

    def _build_message(self, payload: EmailPayload) -> EmailMessage:
        sender = payload.from_address or self.from_address
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = payload.to
        msg["Subject"] = payload.subject
        msg["Message-ID"] = make_msgid(domain=(sender.split("@")[-1] if "@" in sender else None))
        if payload.reply_to:
            msg["Reply-To"] = payload.reply_to
        if payload.cc:
            msg["Cc"] = ", ".join(payload.cc)
        msg.set_content(payload.body_text)
        if payload.body_html:
            msg.add_alternative(payload.body_html, subtype="html")
        return msg

    def _load_aiosmtplib(self):  # type: ignore[no-untyped-def]
        try:
            return importlib.import_module("aiosmtplib")
        except ImportError:
            return None

    def _send_with_smtplib(self, msg: EmailMessage, recipients: list[str]) -> None:
        client: smtplib.SMTP
        if self.use_tls:
            client = smtplib.SMTP_SSL(self.host, self.port, timeout=15.0)
        else:
            client = smtplib.SMTP(self.host, self.port, timeout=15.0)
        try:
            if not self.use_tls:
                client.starttls()
            if self.user and self.password:
                client.login(self.user, self.password)
            client.send_message(msg, to_addrs=recipients)
        finally:
            client.quit()


class SendGridBackend:
    """SendGrid HTTP API backend."""

    def __init__(self, api_key: str, from_address: str) -> None:
        """Build backend. Example: `SendGridBackend('k','from@x.com')`."""

        self.api_key = api_key.strip()
        self.from_address = from_address.strip()

    @classmethod
    def from_env(cls) -> "SendGridBackend":
        """Load config from env. Example: `SendGridBackend.from_env().from_address`."""

        return cls(
            api_key=os.getenv("SENDGRID_API_KEY", ""),
            from_address=os.getenv("SENDGRID_FROM_ADDRESS", ""),
        )

    async def send(self, payload: EmailPayload) -> SendResult:
        """Send one message via SendGrid. Example: `await backend.send(payload)`."""

        if not self.api_key:
            return SendResult(payload.to, "failed", "sendgrid", error="SENDGRID_API_KEY missing.")
        if not self.from_address:
            return SendResult(
                payload.to,
                "failed",
                "sendgrid",
                error="SENDGRID_FROM_ADDRESS missing.",
            )
        content: list[dict[str, str]] = [{"type": "text/plain", "value": payload.body_text}]
        if payload.body_html:
            content.append({"type": "text/html", "value": payload.body_html})
        personalizations: dict[str, Any] = {"to": [{"email": payload.to}]}
        if payload.cc:
            personalizations["cc"] = [{"email": item} for item in payload.cc]
        body: dict[str, Any] = {
            "personalizations": [personalizations],
            "from": {"email": payload.from_address or self.from_address},
            "subject": payload.subject,
            "content": content,
        }
        if payload.reply_to:
            body["reply_to"] = {"email": payload.reply_to}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    json=body,
                    headers=headers,
                )
            if response.status_code == 202:
                return SendResult(
                    payload.to,
                    "sent",
                    "sendgrid",
                    message_id=response.headers.get("X-Message-Id"),
                )
            return SendResult(
                payload.to,
                "failed",
                "sendgrid",
                error=f"HTTP {response.status_code}: {response.text}",
            )
        except Exception as exc:  # pragma: no cover - defensive transport wrapper
            return SendResult(payload.to, "failed", "sendgrid", error=str(exc))


def build_email_backend_from_env() -> EmailBackend:
    """Select backend from `EMAIL_BACKEND`. Example: `build_email_backend_from_env()`."""

    backend = os.getenv("EMAIL_BACKEND", "smtp").strip().lower()
    if backend == "sendgrid":
        return SendGridBackend.from_env()
    return SMTPBackend.from_env()


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}
