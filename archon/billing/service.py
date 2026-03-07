"""Billing service orchestration for customers, subscriptions, metering, and invoices."""

from __future__ import annotations

import time
from dataclasses import asdict
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from archon.analytics.collector import AnalyticsCollector
from archon.billing.models import (
    BillingCustomer,
    BillingInvoice,
    BillingSubscription,
    SubscriptionChange,
    UsageRecord,
    get_plan,
    list_plans,
)
from archon.billing.pricing import invoice_lines_for_usage, subscription_segments
from archon.billing.store import BillingStore
from archon.billing.stripe_gateway import StripeGateway
from archon.billing.webhooks import StripeWebhookVerifier
from archon.core.approval_gate import ApprovalGate, EventSink


class BillingService:
    """High-level billing service for tenant-scoped mutations and invoicing."""

    def __init__(
        self,
        store: BillingStore | None = None,
        *,
        approval_gate: ApprovalGate | None = None,
        collector: AnalyticsCollector | None = None,
        gateway: StripeGateway | None = None,
        webhook_verifier: StripeWebhookVerifier | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.store = store or BillingStore()
        self.approval_gate = approval_gate or ApprovalGate()
        self.collector = collector
        self.gateway = gateway
        self.webhook_verifier = webhook_verifier
        self._clock = clock or time.time

    def plans(self) -> list[dict[str, Any]]:
        """Return the plan catalog as JSON-safe rows.

        Example:
            >>> BillingService(store=BillingStore(":memory:")).plans()[0]["plan_id"]
            'free'
        """

        return [asdict(plan) for plan in list_plans()]

    def summary(self, tenant_id: str) -> dict[str, Any]:
        """Return current customer, subscription, usage, and invoices for one tenant."""

        subscription = self.store.get_subscription(tenant_id)
        cycle_start, cycle_end = _month_period(self._clock())
        if subscription is not None:
            cycle_start, cycle_end = subscription.period_start, subscription.period_end
        usage = self.store.list_usage(tenant_id, start=cycle_start, end=cycle_end)
        return {
            "customer": _customer_dict(self.store.get_customer(tenant_id)),
            "subscription": _subscription_dict(subscription),
            "usage_summary": _usage_summary(usage),
            "recent_invoices": [_invoice_dict(row) for row in self.store.list_invoices(tenant_id, limit=10)],
        }

    async def upsert_customer(
        self,
        *,
        tenant_id: str,
        email: str = "",
        name: str = "",
        metadata: dict[str, Any] | None = None,
        sync_external: bool = False,
        event_sink: EventSink | None = None,
    ) -> BillingCustomer:
        """Create or update a tenant billing customer."""

        current = self.store.get_customer(tenant_id)
        now = float(self._clock())
        customer = current or BillingCustomer(tenant_id=tenant_id, created_at=now, updated_at=now)
        customer.email = str(email or customer.email)
        customer.name = str(name or customer.name)
        customer.metadata = dict(metadata or customer.metadata)
        customer.updated_at = now
        if sync_external:
            customer = await self._sync_customer(customer, event_sink=event_sink)
        saved = self.store.upsert_customer(customer)
        self._emit(
            "billing_customer_upserted",
            tenant_id,
            {"email": saved.email, "name": saved.name},
        )
        return saved

    async def change_subscription(
        self,
        *,
        tenant_id: str,
        plan_id: str,
        effective_at: float | None = None,
        sync_external: bool = False,
        event_sink: EventSink | None = None,
    ) -> BillingSubscription:
        """Create or change the active subscription for one tenant."""

        plan = get_plan(plan_id)
        now = float(self._clock())
        start, end = _month_period(now)
        current = self.store.get_subscription(tenant_id)
        subscription = current or BillingSubscription(
            tenant_id=tenant_id,
            plan_id=plan.plan_id,
            period_start=start,
            period_end=end,
            created_at=now,
            updated_at=now,
        )
        subscription.plan_id = plan.plan_id
        subscription.updated_at = now
        if subscription.period_end <= now:
            subscription.period_start, subscription.period_end = _month_period(now)
        change = SubscriptionChange(
            tenant_id=tenant_id,
            plan_id=plan.plan_id,
            effective_at=float(effective_at or now),
        )
        self.store.record_subscription_change(change)
        if sync_external:
            subscription = await self._sync_subscription(subscription, event_sink=event_sink)
        saved = self.store.upsert_subscription(subscription)
        self._emit(
            "billing_subscription_changed",
            tenant_id,
            {"plan_id": saved.plan_id, "effective_at": change.effective_at},
        )
        return saved

    async def record_usage(
        self,
        *,
        tenant_id: str,
        meter_type: str,
        quantity: float,
        amount_usd: float,
        provider: str = "",
        model: str = "",
        action_type: str = "",
        task_id: str = "",
        timestamp: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UsageRecord:
        """Append one metered usage record."""

        row = UsageRecord(
            tenant_id=tenant_id,
            meter_type=str(meter_type),
            quantity=float(quantity),
            amount_usd=float(amount_usd),
            provider=str(provider),
            model=str(model),
            action_type=str(action_type),
            task_id=str(task_id),
            timestamp=float(timestamp if timestamp is not None else self._clock()),
            metadata=dict(metadata or {}),
        )
        saved = self.store.record_usage(row)
        self._emit(
            "billing_usage_recorded",
            tenant_id,
            {
                "meter_type": saved.meter_type,
                "quantity": saved.quantity,
                "amount_usd": saved.amount_usd,
                "provider": saved.provider,
                "model": saved.model,
                "action_type": saved.action_type,
                "task_id": saved.task_id,
            },
        )
        return saved

    async def record_provider_model_spend(
        self,
        *,
        tenant_id: str,
        task_id: str,
        cost_by_provider_model: dict[str, float],
    ) -> list[UsageRecord]:
        """Record provider/model spend rows from orchestration budget snapshots."""

        rows: list[UsageRecord] = []
        for key, amount in sorted(cost_by_provider_model.items()):
            provider, _, model = str(key).partition("/")
            rows.append(
                await self.record_usage(
                    tenant_id=tenant_id,
                    meter_type="model_spend",
                    quantity=1.0,
                    amount_usd=float(amount),
                    provider=provider,
                    model=model,
                    task_id=task_id,
                )
            )
        return rows

    async def record_outbound_action(
        self,
        *,
        tenant_id: str,
        action_type: str,
        provider: str = "",
        quantity: float = 1.0,
        task_id: str = "",
    ) -> UsageRecord:
        """Record one outbound action meter."""

        return await self.record_usage(
            tenant_id=tenant_id,
            meter_type="outbound_action",
            quantity=float(quantity),
            amount_usd=0.0,
            provider=provider,
            action_type=action_type,
            task_id=task_id,
        )

    async def generate_invoice(
        self,
        *,
        tenant_id: str,
        period_start: float | None = None,
        period_end: float | None = None,
        sync_external: bool = False,
        event_sink: EventSink | None = None,
    ) -> BillingInvoice:
        """Generate and persist an invoice for one tenant and billing period."""

        subscription = self.store.get_subscription(tenant_id)
        if subscription is None:
            raise KeyError(f"Tenant '{tenant_id}' has no active subscription.")
        start = float(period_start if period_start is not None else subscription.period_start)
        end = float(period_end if period_end is not None else subscription.period_end)
        changes = self.store.list_subscription_changes(tenant_id, end=end)
        usage = self.store.list_usage(tenant_id, start=start, end=end)
        segments = subscription_segments(
            changes,
            active_plan_id=subscription.plan_id,
            period_start=start,
            period_end=end,
        )
        lines = invoice_lines_for_usage(segments, usage, period_start=start, period_end=end)
        subtotal = round(sum(line.amount_usd for line in lines), 2)
        now = float(self._clock())
        invoice = BillingInvoice(
            tenant_id=tenant_id,
            plan_id=subscription.plan_id,
            subscription_id=subscription.subscription_id,
            period_start=start,
            period_end=end,
            lines=lines,
            subtotal_usd=subtotal,
            tax_usd=0.0,
            total_usd=subtotal,
            metadata={"usage_summary": _usage_summary(usage)},
            created_at=now,
            updated_at=now,
        )
        if sync_external:
            invoice = await self._sync_invoice(invoice, event_sink=event_sink)
        saved = self.store.save_invoice(invoice)
        self._emit(
            "billing_invoice_generated",
            tenant_id,
            {"invoice_id": saved.invoice_id, "total_usd": saved.total_usd},
        )
        return saved

    async def handle_stripe_webhook(self, payload: str, signature_header: str) -> dict[str, Any]:
        """Verify and apply one Stripe webhook payload."""

        if self.webhook_verifier is None:
            raise ValueError("Stripe webhook verifier is not configured.")
        event = self.webhook_verifier.verify(payload, signature_header)
        if self.store.has_processed_webhook(event.event_id):
            return {"status": "ignored", "event_id": event.event_id}
        tenant_id = _tenant_id_from_webhook(event.payload)
        object_payload = ((event.payload.get("data") or {}).get("object") or {}) if isinstance(event.payload, dict) else {}

        if event.event_type == "invoice.paid":
            external_invoice_id = str(object_payload.get("id", "")).strip()
            invoice = self.store.find_invoice_by_external_id(external_invoice_id)
            if invoice is not None:
                self.store.mark_invoice_paid(invoice.invoice_id, paid_at=float(self._clock()))
                tenant_id = tenant_id or invoice.tenant_id
                self._emit("billing_invoice_paid", tenant_id, {"invoice_id": invoice.invoice_id})
        elif event.event_type == "customer.subscription.updated" and tenant_id:
            plan_id = str((((object_payload.get("metadata") or {}).get("plan_id")) or "")).strip() or "growth"
            await self.change_subscription(
                tenant_id=tenant_id,
                plan_id=plan_id,
                effective_at=float(self._clock()),
            )

        self.store.record_webhook(event, status="processed")
        self._emit(
            "billing_webhook_processed",
            tenant_id or "system",
            {"event_type": event.event_type, "event_id": event.event_id},
        )
        return {"status": "processed", "event_id": event.event_id, "tenant_id": tenant_id}

    async def _sync_customer(
        self,
        customer: BillingCustomer,
        *,
        event_sink: EventSink | None,
    ) -> BillingCustomer:
        if self.gateway is None:
            raise RuntimeError("Stripe gateway is not configured.")
        await self._gate(
            "billing_customer_sync",
            customer.tenant_id,
            {"email": customer.email},
            event_sink,
        )
        result = await self.gateway.upsert_customer(customer)
        return replace(customer, external_customer_id=result.external_id)

    async def _sync_subscription(
        self,
        subscription: BillingSubscription,
        *,
        event_sink: EventSink | None,
    ) -> BillingSubscription:
        if self.gateway is None:
            raise RuntimeError("Stripe gateway is not configured.")
        customer = self.store.get_customer(subscription.tenant_id)
        if customer is None:
            customer = await self.upsert_customer(
                tenant_id=subscription.tenant_id,
                sync_external=True,
                event_sink=event_sink,
            )
        if not customer.external_customer_id:
            raise RuntimeError("External customer id is required before syncing subscription.")
        await self._gate(
            "billing_subscription_sync",
            subscription.tenant_id,
            {"plan_id": subscription.plan_id},
            event_sink,
        )
        result = await self.gateway.upsert_subscription(
            customer.external_customer_id,
            subscription,
            get_plan(subscription.plan_id),
        )
        return replace(subscription, external_subscription_id=result.external_id, status=result.status)

    async def _sync_invoice(
        self,
        invoice: BillingInvoice,
        *,
        event_sink: EventSink | None,
    ) -> BillingInvoice:
        if self.gateway is None:
            raise RuntimeError("Stripe gateway is not configured.")
        customer = self.store.get_customer(invoice.tenant_id)
        if customer is None or not customer.external_customer_id:
            customer = await self.upsert_customer(
                tenant_id=invoice.tenant_id,
                sync_external=True,
                event_sink=event_sink,
            )
        await self._gate(
            "billing_invoice_sync",
            invoice.tenant_id,
            {"invoice_id": invoice.invoice_id, "total_usd": invoice.total_usd},
            event_sink,
        )
        result = await self.gateway.create_invoice(customer.external_customer_id or "", invoice)
        return replace(invoice, external_invoice_id=result.external_id, status=result.status)

    async def _gate(
        self,
        action_id: str,
        tenant_id: str,
        payload: dict[str, Any],
        event_sink: EventSink | None,
    ) -> None:
        await self.approval_gate.check(
            action="financial_transaction",
            context={"tenant_id": tenant_id, **dict(payload), "event_sink": event_sink},
            action_id=action_id,
        )

    def _emit(self, event_type: str, tenant_id: str, properties: dict[str, Any]) -> None:
        if self.collector is None:
            return
        self.collector.record(tenant_id=tenant_id, event_type=event_type, properties=properties)


def _month_period(now_ts: float) -> tuple[float, float]:
    current = datetime.fromtimestamp(float(now_ts), tz=timezone.utc)
    start = datetime(current.year, current.month, 1, tzinfo=timezone.utc).timestamp()
    if current.month == 12:
        end_dt = datetime(current.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end_dt = datetime(current.year, current.month + 1, 1, tzinfo=timezone.utc)
    return start, end_dt.timestamp()


def _usage_summary(rows: list[UsageRecord]) -> dict[str, Any]:
    return {
        "model_spend_usd": round(
            sum(row.amount_usd for row in rows if row.meter_type == "model_spend"),
            6,
        ),
        "outbound_actions": round(
            sum(row.quantity for row in rows if row.meter_type == "outbound_action"),
            6,
        ),
    }


def _customer_dict(customer: BillingCustomer | None) -> dict[str, Any] | None:
    return None if customer is None else asdict(customer)


def _subscription_dict(subscription: BillingSubscription | None) -> dict[str, Any] | None:
    return None if subscription is None else asdict(subscription)


def _invoice_dict(invoice: BillingInvoice) -> dict[str, Any]:
    return {
        "invoice_id": invoice.invoice_id,
        "tenant_id": invoice.tenant_id,
        "plan_id": invoice.plan_id,
        "subscription_id": invoice.subscription_id,
        "period_start": invoice.period_start,
        "period_end": invoice.period_end,
        "subtotal_usd": invoice.subtotal_usd,
        "tax_usd": invoice.tax_usd,
        "total_usd": invoice.total_usd,
        "currency": invoice.currency,
        "status": invoice.status,
        "external_invoice_id": invoice.external_invoice_id,
        "metadata": dict(invoice.metadata),
        "lines": [
            {
                "description": line.description,
                "meter_type": line.meter_type,
                "quantity": line.quantity,
                "unit_amount_usd": line.unit_amount_usd,
                "amount_usd": line.amount_usd,
                "metadata": dict(line.metadata),
            }
            for line in invoice.lines
        ],
    }


def _tenant_id_from_webhook(payload: dict[str, Any]) -> str:
    body = ((payload.get("data") or {}).get("object") or {}) if isinstance(payload, dict) else {}
    metadata = body.get("metadata", {}) if isinstance(body, dict) else {}
    if isinstance(metadata, dict):
        return str(metadata.get("tenant_id", "")).strip()
    return ""
