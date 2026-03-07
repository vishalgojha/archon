"""Low-level Stripe HTTP client used for billing and metered usage sync."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _coerce_payload(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _parse_signature_header(signature_header: str) -> tuple[int, list[str]]:
    timestamp = 0
    signatures: list[str] = []
    for part in [item.strip() for item in str(signature_header or "").split(",") if item.strip()]:
        key, _, value = part.partition("=")
        if key == "t":
            timestamp = int(value or "0")
        elif key == "v1" and value:
            signatures.append(value)
    if timestamp <= 0 or not signatures:
        raise ValueError("Invalid Stripe-Signature header.")
    return timestamp, signatures


@dataclass(slots=True, frozen=True)
class StripeCustomer:
    """One Stripe customer projection.

    Example:
        >>> StripeCustomer(customer_id="cus_123", tenant_id="tenant-a", email="ops@example.com").tenant_id
        'tenant-a'
    """

    customer_id: str
    tenant_id: str
    email: str
    name: str = ""


@dataclass(slots=True, frozen=True)
class StripeSubscription:
    """One Stripe subscription projection.

    Example:
        >>> StripeSubscription(sub_id="sub_123", status="active", current_period_end=10.0).status
        'active'
    """

    sub_id: str
    status: str
    current_period_end: float
    customer_id: str = ""
    price_id: str = ""


@dataclass(slots=True, frozen=True)
class UsageRecord:
    """One Stripe usage record response.

    Example:
        >>> UsageRecord(record_id="ur_1", subscription_item_id="si_1", quantity=2.0, timestamp=1.0).quantity
        2.0
    """

    record_id: str
    subscription_item_id: str
    quantity: float
    timestamp: float
    livemode: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class StripeInvoice:
    """One Stripe invoice document summary.

    Example:
        >>> StripeInvoice("in_1", 2500, "usd", "paid", "", 1.0, 2.0).amount_cents
        2500
    """

    invoice_id: str
    amount_cents: int
    currency: str
    status: str
    pdf_url: str
    period_start: float
    period_end: float


@dataclass(slots=True, frozen=True)
class WebhookEvent:
    """Verified Stripe webhook event envelope.

    Example:
        >>> WebhookEvent("evt_1", "invoice.paid", {"object": "event"}, 1.0).event_type
        'invoice.paid'
    """

    event_id: str
    event_type: str
    data: dict[str, Any]
    created_at: float


class StripeClient:
    """Minimal Stripe API client using `httpx` and form-encoded payloads.

    Example:
        >>> client = StripeClient(secret_key="sk_test", http_client=httpx.AsyncClient())
        >>> client.base_url
        'https://api.stripe.com/v1'
    """

    def __init__(
        self,
        secret_key: str | None = None,
        *,
        webhook_secret: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.stripe.com/v1",
        timeout_seconds: float = 30.0,
        tolerance_seconds: int = 300,
    ) -> None:
        self.secret_key = str(
            secret_key
            or os.getenv("STRIPE_SECRET_KEY")
            or os.getenv("ARCHON_STRIPE_SECRET_KEY")
            or ""
        ).strip()
        self.webhook_secret = str(
            webhook_secret
            or os.getenv("STRIPE_WEBHOOK_SECRET")
            or os.getenv("ARCHON_STRIPE_WEBHOOK_SECRET")
            or ""
        ).strip()
        self.base_url = base_url.rstrip("/")
        self.tolerance_seconds = max(1, int(tolerance_seconds))
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        """Close the underlying HTTP client when owned by this instance.

        Example:
            >>> client = StripeClient(secret_key="sk_test")
            >>> __import__("asyncio").run(client.aclose()) is None
            True
        """

        if self._owns_http_client:
            await self._http.aclose()

    async def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """POST one form-encoded request.

        Example:
            >>> hasattr(StripeClient, "_post")
            True
        """

        headers = {"Authorization": f"Bearer {self.secret_key}"}
        response = await self._http.post(
            f"{self.base_url}{path}",
            headers=headers,
            data={key: value for key, value in data.items() if value is not None},
        )
        response.raise_for_status()
        return _coerce_payload(response.json())

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET one Stripe resource request.

        Example:
            >>> hasattr(StripeClient, "_get")
            True
        """

        headers = {"Authorization": f"Bearer {self.secret_key}"}
        response = await self._http.get(
            f"{self.base_url}{path}",
            headers=headers,
            params={key: value for key, value in params.items() if value is not None},
        )
        response.raise_for_status()
        return _coerce_payload(response.json())

    async def create_customer(self, tenant_id: str, email: str, name: str) -> StripeCustomer:
        """Create one Stripe customer.

        Example:
            >>> hasattr(StripeClient, "create_customer")
            True
        """

        payload = await self._post(
            "/customers",
            {
                "email": str(email or "").strip(),
                "name": str(name or "").strip(),
                "metadata[tenant_id]": str(tenant_id or "").strip(),
            },
        )
        return StripeCustomer(
            customer_id=str(payload.get("id") or _identifier("cus")),
            tenant_id=str(((payload.get("metadata") or {}).get("tenant_id")) or tenant_id),
            email=str(payload.get("email") or email),
            name=str(payload.get("name") or name),
        )

    async def create_subscription(self, customer_id: str, price_id: str) -> StripeSubscription:
        """Create one Stripe subscription.

        Example:
            >>> hasattr(StripeClient, "create_subscription")
            True
        """

        payload = await self._post(
            "/subscriptions",
            {"customer": customer_id, "items[0][price]": price_id},
        )
        return StripeSubscription(
            sub_id=str(payload.get("id") or _identifier("sub")),
            status=str(payload.get("status") or "active"),
            current_period_end=float(payload.get("current_period_end") or time.time()),
            customer_id=str(payload.get("customer") or customer_id),
            price_id=_subscription_price_id(payload, default=price_id),
        )

    async def cancel_subscription(self, sub_id: str) -> StripeSubscription:
        """Cancel one Stripe subscription at period end.

        Example:
            >>> hasattr(StripeClient, "cancel_subscription")
            True
        """

        payload = await self._post(f"/subscriptions/{sub_id}", {"cancel_at_period_end": "true"})
        return StripeSubscription(
            sub_id=str(payload.get("id") or sub_id),
            status=str(payload.get("status") or "canceled"),
            current_period_end=float(payload.get("current_period_end") or time.time()),
            customer_id=str(payload.get("customer") or ""),
            price_id=_subscription_price_id(payload),
        )

    async def create_usage_record(
        self,
        subscription_item_id: str,
        quantity: float,
        timestamp: float,
    ) -> UsageRecord:
        """Create one metered usage record on a Stripe subscription item.

        Example:
            >>> hasattr(StripeClient, "create_usage_record")
            True
        """

        payload = await self._post(
            f"/subscription_items/{subscription_item_id}/usage_records",
            {
                "quantity": float(quantity),
                "timestamp": int(float(timestamp)),
                "action": "increment",
            },
        )
        return UsageRecord(
            record_id=str(payload.get("id") or _identifier("ur")),
            subscription_item_id=str(payload.get("subscription_item") or subscription_item_id),
            quantity=float(payload.get("quantity") or quantity),
            timestamp=float(payload.get("timestamp") or timestamp),
            livemode=bool(payload.get("livemode", False)),
            metadata=_coerce_payload(payload.get("metadata")),
        )

    async def list_invoices(self, customer_id: str, limit: int = 10) -> list[StripeInvoice]:
        """List recent invoices for one Stripe customer.

        Example:
            >>> hasattr(StripeClient, "list_invoices")
            True
        """

        payload = await self._get(
            "/invoices",
            {"customer": customer_id, "limit": max(1, min(int(limit), 100))},
        )
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            return []
        return [
            StripeInvoice(
                invoice_id=str(row.get("id") or _identifier("in")),
                amount_cents=int(row.get("amount_due") or row.get("total") or 0),
                currency=str(row.get("currency") or "usd"),
                status=str(row.get("status") or "draft"),
                pdf_url=str(row.get("invoice_pdf") or ""),
                period_start=float(
                    (row.get("period_start") or _invoice_period(row).get("start") or 0.0)
                ),
                period_end=float((row.get("period_end") or _invoice_period(row).get("end") or 0.0)),
            )
            for row in rows
            if isinstance(row, dict)
        ]

    def construct_webhook_event(self, payload_bytes: bytes, sig_header: str) -> WebhookEvent:
        """Validate a Stripe signature header and parse one event payload.

        Example:
            >>> client = StripeClient(secret_key="sk", webhook_secret="whsec")
            >>> hasattr(client, "construct_webhook_event")
            True
        """

        if not self.webhook_secret:
            raise ValueError("Stripe webhook secret is not configured.")
        payload_text = payload_bytes.decode("utf-8")
        timestamp, signatures = _parse_signature_header(sig_header)
        if abs(int(time.time()) - timestamp) > self.tolerance_seconds:
            raise ValueError("Webhook signature timestamp outside allowed tolerance.")
        signed = f"{timestamp}.{payload_text}".encode("utf-8")
        digest = hmac.new(self.webhook_secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(digest, candidate) for candidate in signatures):
            raise ValueError("Webhook signature mismatch.")
        payload = json.loads(payload_text)
        if not isinstance(payload, dict):
            raise ValueError("Webhook payload must be a JSON object.")
        event_id = str(payload.get("id") or "").strip()
        event_type = str(payload.get("type") or "").strip()
        if not event_id or not event_type:
            raise ValueError("Webhook payload missing id/type.")
        return WebhookEvent(
            event_id=event_id,
            event_type=event_type,
            data=payload,
            created_at=float(payload.get("created") or timestamp),
        )


def _subscription_price_id(payload: dict[str, Any], default: str = "") -> str:
    items = ((payload.get("items") or {}).get("data") or []) if isinstance(payload, dict) else []
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict):
            price = first.get("price") or {}
            if isinstance(price, dict):
                return str(price.get("id") or default)
    return str(default or "")


def _invoice_period(payload: dict[str, Any]) -> dict[str, Any]:
    lines = ((payload.get("lines") or {}).get("data") or []) if isinstance(payload, dict) else []
    if isinstance(lines, list) and lines:
        first = lines[0]
        if isinstance(first, dict):
            period = first.get("period") or {}
            return period if isinstance(period, dict) else {}
    return {}
