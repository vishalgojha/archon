"""Stripe webhook signature verification helpers and FastAPI handlers."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request

from archon.billing.models import WebhookEvent
from archon.billing.stripe_client import StripeClient
from archon.billing.stripe_client import WebhookEvent as StripeClientWebhookEvent


def build_stripe_signature_header(
    payload: str,
    secret: str,
    *,
    timestamp: int | None = None,
) -> str:
    """Build a Stripe-compatible `Stripe-Signature` header for tests.

    Example:
        >>> header = build_stripe_signature_header('{"id":"evt_1","type":"invoice.paid"}', "whsec_test", timestamp=100)
        >>> header.startswith("t=100,v1=")
        True
    """

    issued_at = int(time.time() if timestamp is None else timestamp)
    signed_payload = f"{issued_at}.{payload}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={issued_at},v1={digest}"


class StripeWebhookVerifier:
    """Verify Stripe webhook signatures and parse event payloads."""

    def __init__(
        self,
        secret: str,
        *,
        tolerance_seconds: int = 300,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.secret = str(secret or "").strip()
        self.tolerance_seconds = int(tolerance_seconds)
        self._clock = clock or time.time

    def verify(self, payload: str, signature_header: str) -> WebhookEvent:
        """Verify one webhook payload and return normalized event metadata.

        Example:
            >>> verifier = StripeWebhookVerifier("whsec_test", tolerance_seconds=300, clock=lambda: 100.0)
            >>> header = build_stripe_signature_header('{"id":"evt_1","type":"invoice.paid"}', "whsec_test", timestamp=100)
            >>> verifier.verify('{"id":"evt_1","type":"invoice.paid"}', header).event_type
            'invoice.paid'
        """

        if not self.secret:
            raise ValueError("Stripe webhook secret is not configured.")
        timestamp, signatures = _parse_signature_header(signature_header)
        current = int(float(self._clock()))
        if abs(current - timestamp) > self.tolerance_seconds:
            raise ValueError("Webhook signature timestamp outside allowed tolerance.")

        expected = build_stripe_signature_header(payload, self.secret, timestamp=timestamp).split(
            ",v1=", 1
        )[1]
        if not any(hmac.compare_digest(expected, signature) for signature in signatures):
            raise ValueError("Webhook signature mismatch.")

        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise ValueError("Webhook payload must be a JSON object.")
        event_id = str(parsed.get("id", "")).strip()
        event_type = str(parsed.get("type", "")).strip()
        if not event_id or not event_type:
            raise ValueError("Webhook payload missing id/type.")
        created_at = float(parsed.get("created") or timestamp)
        return WebhookEvent(
            event_id=event_id,
            event_type=event_type,
            payload=parsed,
            created_at=created_at,
        )


def _parse_signature_header(signature_header: str) -> tuple[int, list[str]]:
    parts = [item.strip() for item in str(signature_header or "").split(",") if item.strip()]
    timestamp = 0
    signatures: list[str] = []
    for part in parts:
        key, _, value = part.partition("=")
        if key == "t":
            timestamp = int(value or "0")
        elif key == "v1" and value:
            signatures.append(value)
    if timestamp <= 0 or not signatures:
        raise ValueError("Invalid Stripe-Signature header.")
    return timestamp, signatures


class StripeWebhookHandler:
    """Process verified Stripe webhook events into local billing state.

    Example:
        >>> handler = StripeWebhookHandler()
        >>> isinstance(handler.router(), APIRouter)
        True
    """

    def __init__(
        self,
        *,
        stripe_client: StripeClient | None = None,
        billing_service: Any | None = None,
        collector: Any | None = None,
        dunning_notifier: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> None:
        self.stripe_client = stripe_client or StripeClient()
        self.billing_service = billing_service
        self.collector = collector
        self.dunning_notifier = dunning_notifier

    async def handle(self, payload_bytes: bytes, sig_header: str) -> dict[str, Any]:
        """Validate and process one Stripe webhook request.

        Example:
            >>> handler = StripeWebhookHandler()
            >>> hasattr(handler, "handle")
            True
        """

        event = self.stripe_client.construct_webhook_event(payload_bytes, sig_header)
        store = getattr(self.billing_service, "store", None)
        if store is not None and callable(getattr(store, "has_processed_webhook", None)):
            if bool(store.has_processed_webhook(event.event_id)):
                return {"status": "ignored", "event_id": event.event_id}

        object_payload = _event_object(event)
        tenant_id = _event_tenant_id(event) or _invoice_tenant_id(store, object_payload)

        if event.event_type == "invoice.paid":
            await self._handle_invoice_paid(store, object_payload, tenant_id)
        elif event.event_type == "invoice.payment_failed":
            await self._handle_invoice_failed(store, object_payload, tenant_id)
        elif event.event_type == "customer.subscription.deleted":
            await self._handle_subscription_deleted(tenant_id)
        elif event.event_type == "customer.subscription.updated":
            await self._handle_subscription_updated(tenant_id, object_payload)

        if store is not None and callable(getattr(store, "record_webhook", None)):
            store.record_webhook(
                WebhookEvent(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    payload=event.data,
                    created_at=event.created_at,
                ),
                status="processed",
            )
        self._emit(
            tenant_id or "system",
            "billing_webhook_processed",
            {"event_id": event.event_id, "event_type": event.event_type},
        )
        return {
            "status": "processed",
            "event_id": event.event_id,
            "event_type": event.event_type,
            "tenant_id": tenant_id,
        }

    def router(self) -> APIRouter:
        """Build the standalone Stripe webhook router.

        Example:
            >>> isinstance(StripeWebhookHandler().router(), APIRouter)
            True
        """

        router = APIRouter(prefix="/billing/webhooks", tags=["billing"])

        @router.post("/stripe")
        async def stripe_webhook(request: Request) -> dict[str, Any]:
            signature = request.headers.get("stripe-signature", "")
            try:
                return await self.handle(await request.body(), signature)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return router

    async def _handle_invoice_paid(
        self,
        store: Any,
        object_payload: dict[str, Any],
        tenant_id: str,
    ) -> None:
        invoice = _invoice_from_payload(store, object_payload)
        if invoice is not None and callable(getattr(store, "mark_invoice_paid", None)):
            store.mark_invoice_paid(invoice.invoice_id, paid_at=time.time())
            tenant_id = tenant_id or getattr(invoice, "tenant_id", "")
        self._emit(
            tenant_id or "system",
            "billing_invoice_paid",
            {"invoice_id": _object_id(object_payload)},
        )

    async def _handle_invoice_failed(
        self,
        store: Any,
        object_payload: dict[str, Any],
        tenant_id: str,
    ) -> None:
        invoice = _invoice_from_payload(store, object_payload)
        if invoice is not None and callable(getattr(store, "update_invoice_status", None)):
            store.update_invoice_status(
                invoice.invoice_id,
                status="payment_failed",
                updated_at=time.time(),
            )
            tenant_id = tenant_id or getattr(invoice, "tenant_id", "")
        self._emit(
            tenant_id or "system",
            "billing_invoice_payment_failed",
            {"invoice_id": _object_id(object_payload)},
        )
        if callable(self.dunning_notifier):
            maybe = self.dunning_notifier(
                {
                    "tenant_id": tenant_id,
                    "event_type": "invoice.payment_failed",
                    "invoice_id": _object_id(object_payload),
                }
            )
            if hasattr(maybe, "__await__"):
                await maybe
        self._emit(
            tenant_id or "system",
            "billing_dunning_triggered",
            {"invoice_id": _object_id(object_payload)},
        )

    async def _handle_subscription_deleted(self, tenant_id: str) -> None:
        if tenant_id and callable(getattr(self.billing_service, "change_subscription", None)):
            await self.billing_service.change_subscription(
                tenant_id=tenant_id,
                plan_id="free",
                effective_at=time.time(),
            )
        self._emit(tenant_id or "system", "billing_tier_downgraded", {"plan_id": "free"})

    async def _handle_subscription_updated(
        self,
        tenant_id: str,
        object_payload: dict[str, Any],
    ) -> None:
        plan_id = _plan_id_from_subscription(object_payload)
        if (
            tenant_id
            and plan_id
            and callable(getattr(self.billing_service, "change_subscription", None))
        ):
            await self.billing_service.change_subscription(
                tenant_id=tenant_id,
                plan_id=plan_id,
                effective_at=time.time(),
            )
        self._emit(
            tenant_id or "system",
            "billing_subscription_synced",
            {"plan_id": plan_id or "unknown"},
        )

    def _emit(self, tenant_id: str, event_type: str, properties: dict[str, Any]) -> None:
        if self.collector is None or not callable(getattr(self.collector, "record", None)):
            return
        try:
            self.collector.record(tenant_id=tenant_id, event_type=event_type, properties=properties)
        except Exception:
            return


def create_router() -> APIRouter:
    """Create the standalone Stripe webhook router from `app.state`.

    Example:
        >>> isinstance(create_router(), APIRouter)
        True
    """

    router = APIRouter(prefix="/billing/webhooks", tags=["billing"])

    @router.post("/stripe")
    async def stripe_webhook(request: Request) -> dict[str, Any]:
        handler = getattr(request.app.state, "stripe_webhook_handler", None)
        if handler is None or not callable(getattr(handler, "handle", None)):
            raise HTTPException(status_code=503, detail="Stripe webhook handler is unavailable.")
        signature = request.headers.get("stripe-signature", "")
        try:
            return await handler.handle(await request.body(), signature)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router


def _event_object(event: StripeClientWebhookEvent) -> dict[str, Any]:
    payload = event.data if isinstance(event.data, dict) else {}
    data = payload.get("data") or {}
    if isinstance(data, dict):
        obj = data.get("object") or {}
        if isinstance(obj, dict):
            return obj
    return {}


def _event_tenant_id(event: StripeClientWebhookEvent) -> str:
    return _tenant_id_from_object(_event_object(event))


def _tenant_id_from_object(payload: dict[str, Any]) -> str:
    metadata = payload.get("metadata") or {}
    if isinstance(metadata, dict):
        return str(metadata.get("tenant_id") or "").strip()
    return ""


def _invoice_tenant_id(store: Any, payload: dict[str, Any]) -> str:
    invoice = _invoice_from_payload(store, payload)
    return str(getattr(invoice, "tenant_id", "")).strip() if invoice is not None else ""


def _invoice_from_payload(store: Any, payload: dict[str, Any]) -> Any | None:
    if store is None:
        return None
    external_invoice_id = _object_id(payload)
    finder = getattr(store, "find_invoice_by_external_id", None)
    if callable(finder) and external_invoice_id:
        return finder(external_invoice_id)
    return None


def _object_id(payload: dict[str, Any]) -> str:
    return str(payload.get("id") or "").strip()


def _plan_id_from_subscription(payload: dict[str, Any]) -> str:
    metadata = payload.get("metadata") or {}
    if isinstance(metadata, dict):
        candidate = str(metadata.get("plan_id") or "").strip().lower()
        if candidate:
            return candidate
    price_id = _subscription_price_id(payload)
    for candidate in ("enterprise", "business", "growth", "free"):
        if candidate in price_id:
            return "enterprise" if candidate == "enterprise" else candidate
    return "growth" if price_id else ""


def _subscription_price_id(payload: dict[str, Any]) -> str:
    items = ((payload.get("items") or {}).get("data") or []) if isinstance(payload, dict) else []
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict):
            price = first.get("price") or {}
            if isinstance(price, dict):
                return str(price.get("id") or "").strip().lower()
    return ""
