"""WhatsApp transport backends for Twilio and Meta APIs."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass(slots=True)
class TemplateMessage:
    """Template payload for Meta WABA sends.

    Example: `TemplateMessage("order_update", "en_US", [])`.
    """

    template_name: str
    language_code: str
    components: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class SendResult:
    """Outbound WhatsApp send result.

    Example: `SendResult("+1", "sent", "twilio").ok`.
    """

    to: str
    status: str
    provider: str
    provider_message_id: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True when send status is successful.

        Example: `SendResult("+1", "sent", "meta").ok`.
        """

        return self.status == "sent"


class WhatsAppBackend(Protocol):
    """Transport contract for WhatsApp providers."""

    async def send_text(self, to: str, body: str) -> SendResult:
        """Send text message."""

    async def send_template(self, to: str, template: TemplateMessage) -> SendResult:
        """Send template message."""


class TwilioBackend:
    """Twilio WhatsApp transport."""

    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self.account_sid = account_sid.strip()
        self.auth_token = auth_token.strip()
        self.from_number = ensure_whatsapp_prefix(from_number.strip())

    @classmethod
    def from_env(cls) -> "TwilioBackend":
        """Build Twilio backend from environment variables.

        Example: `TwilioBackend.from_env().account_sid`.
        """

        return cls(
            account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
            auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            from_number=os.getenv("TWILIO_WHATSAPP_FROM", ""),
        )

    async def send_text(self, to: str, body: str) -> SendResult:
        """Send one text message via Twilio WABA.

        Example: `await backend.send_text("+1555", "Hello")`.
        """

        to_number = ensure_whatsapp_prefix(to)
        if not self.account_sid or not self.auth_token or not self.from_number:
            return SendResult(
                to=to_number,
                status="failed",
                provider="twilio",
                error="Twilio config missing account_sid/auth_token/from_number.",
            )

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        payload = {"To": to_number, "From": self.from_number, "Body": body}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, data=payload, auth=(self.account_sid, self.auth_token))
            if response.status_code in {200, 201}:
                data = _safe_json(response)
                return SendResult(
                    to=to_number,
                    status="sent",
                    provider="twilio",
                    provider_message_id=str(data.get("sid", "")) or None,
                )
            return SendResult(
                to=to_number,
                status="failed",
                provider="twilio",
                error=f"HTTP {response.status_code}: {response.text}",
            )
        except Exception as exc:  # pragma: no cover
            return SendResult(to=to_number, status="failed", provider="twilio", error=str(exc))

    async def send_template(self, to: str, template: TemplateMessage) -> SendResult:
        """Fallback template send for Twilio by rendering an inline marker string.

        Example: `await backend.send_template("+1555", TemplateMessage(...))`.
        """

        rendered = f"[template:{template.template_name}/{template.language_code}]"
        if template.components:
            rendered += f" {template.components}"
        return await self.send_text(to, rendered)


class MetaBackend:
    """Meta Graph API transport for WhatsApp Business."""

    def __init__(self, access_token: str, phone_number_id: str) -> None:
        self.access_token = access_token.strip()
        self.phone_number_id = phone_number_id.strip()

    @classmethod
    def from_env(cls) -> "MetaBackend":
        """Build Meta backend from environment variables.

        Example: `MetaBackend.from_env().phone_number_id`.
        """

        return cls(
            access_token=os.getenv("WHATSAPP_ACCESS_TOKEN", ""),
            phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
        )

    async def send_text(self, to: str, body: str) -> SendResult:
        """Send one text message via Meta WABA.

        Example: `await backend.send_text("+1555", "Hello")`.
        """

        payload = {
            "messaging_product": "whatsapp",
            "to": strip_whatsapp_prefix(to),
            "type": "text",
            "text": {"body": body},
        }
        return await self._post_messages(payload, to)

    async def send_template(self, to: str, template: TemplateMessage) -> SendResult:
        """Send one template message via Meta WABA.

        Example: `await backend.send_template("+1555", TemplateMessage(...))`.
        """

        payload = {
            "messaging_product": "whatsapp",
            "to": strip_whatsapp_prefix(to),
            "type": "template",
            "template": {
                "name": template.template_name,
                "language": {"code": template.language_code},
                "components": template.components,
            },
        }
        return await self._post_messages(payload, to)

    async def _post_messages(self, payload: dict[str, Any], to: str) -> SendResult:
        """Post payload to Meta Graph API and normalize the provider response.

        Example: `await backend._post_messages({}, "+1555")`.
        """

        if not self.access_token or not self.phone_number_id:
            return SendResult(
                to=strip_whatsapp_prefix(to),
                status="failed",
                provider="meta",
                error="Meta config missing access_token/phone_number_id.",
            )

        url = f"https://graph.facebook.com/v19.0/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=payload, headers=headers)
            if 200 <= response.status_code < 300:
                data = _safe_json(response)
                provider_id = None
                messages = data.get("messages")
                if isinstance(messages, list) and messages:
                    provider_id = str(messages[0].get("id", "")) or None
                return SendResult(
                    to=strip_whatsapp_prefix(to),
                    status="sent",
                    provider="meta",
                    provider_message_id=provider_id,
                )
            return SendResult(
                to=strip_whatsapp_prefix(to),
                status="failed",
                provider="meta",
                error=f"HTTP {response.status_code}: {response.text}",
            )
        except Exception as exc:  # pragma: no cover
            return SendResult(to=strip_whatsapp_prefix(to), status="failed", provider="meta", error=str(exc))


def build_whatsapp_backend_from_env() -> WhatsAppBackend:
    """Select backend from `WHATSAPP_BACKEND` with `twilio` as default.

    Example: `build_whatsapp_backend_from_env()`.
    """

    backend = os.getenv("WHATSAPP_BACKEND", "twilio").strip().lower()
    if backend == "meta":
        return MetaBackend.from_env()
    return TwilioBackend.from_env()


def ensure_whatsapp_prefix(value: str) -> str:
    """Ensure a number starts with `whatsapp:`.

    Example: `ensure_whatsapp_prefix("+1555")`.
    """

    raw = value.strip()
    if not raw:
        return ""
    return raw if raw.lower().startswith("whatsapp:") else f"whatsapp:{raw}"


def strip_whatsapp_prefix(value: str) -> str:
    """Remove `whatsapp:` prefix from a number.

    Example: `strip_whatsapp_prefix("whatsapp:+1555")`.
    """

    raw = value.strip()
    if raw.lower().startswith("whatsapp:"):
        return raw.split(":", 1)[1]
    return raw


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
