"""Tests for billing pricing, approval gating, and webhook verification."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from archon.billing import BillingService, BillingStore, StripeGateway, StripeWebhookVerifier
from archon.billing.models import BillingSubscription, SubscriptionChange
from archon.billing.webhooks import build_stripe_signature_header
from archon.core.approval_gate import ApprovalRequiredError


def _tmp_db(name: str) -> Path:
    root = Path("archon/tests/_tmp_billing")
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{name}-{uuid.uuid4().hex[:8]}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "billing.sqlite3"


@pytest.mark.asyncio
async def test_invoice_generation_prorates_plan_fees_and_overages() -> None:
    db_path = _tmp_db("invoice")
    store = BillingStore(path=db_path)
    service = BillingService(store=store, clock=lambda: 30.0)

    store.upsert_subscription(
        BillingSubscription(
            tenant_id="tenant-a",
            plan_id="business",
            period_start=0.0,
            period_end=30.0,
            created_at=0.0,
            updated_at=0.0,
        )
    )
    store.record_subscription_change(SubscriptionChange("tenant-a", "growth", 0.0))
    store.record_subscription_change(SubscriptionChange("tenant-a", "business", 15.0))
    await service.record_usage(
        tenant_id="tenant-a",
        meter_type="model_spend",
        quantity=1.0,
        amount_usd=80.0,
        provider="openai",
        model="gpt-4o",
        timestamp=5.0,
    )
    await service.record_usage(
        tenant_id="tenant-a",
        meter_type="model_spend",
        quantity=1.0,
        amount_usd=20.0,
        provider="anthropic",
        model="claude-sonnet-4-5",
        timestamp=10.0,
    )
    await service.record_usage(
        tenant_id="tenant-a",
        meter_type="outbound_action",
        quantity=3000.0,
        amount_usd=0.0,
        action_type="outbound_email",
        timestamp=12.0,
    )

    invoice = await service.generate_invoice(
        tenant_id="tenant-a",
        period_start=0.0,
        period_end=30.0,
    )

    assert invoice.subtotal_usd == 165.25
    assert invoice.total_usd == 165.25
    assert [line.meter_type for line in invoice.lines].count("plan_base") == 2
    model_lines = [line for line in invoice.lines if line.meter_type == "model_spend"]
    assert sum(line.amount_usd for line in model_lines) == 37.5
    outbound_lines = [line for line in invoice.lines if line.meter_type == "outbound_action"]
    assert outbound_lines[0].amount_usd == 3.75


@pytest.mark.asyncio
async def test_sync_external_customer_requires_approval_unless_auto_resolved() -> None:
    db_path = _tmp_db("approval")
    gateway = StripeGateway(api_key="sk_test_123", live_mode=False)
    service = BillingService(store=BillingStore(path=db_path), gateway=gateway)

    with pytest.raises(ApprovalRequiredError):
        await service.upsert_customer(
            tenant_id="tenant-a",
            email="owner@example.com",
            sync_external=True,
        )

    async def sink(event: dict[str, object]) -> None:
        service.approval_gate.approve(str(event["request_id"]), approver="tester", notes="ok")

    customer = await service.upsert_customer(
        tenant_id="tenant-a",
        email="owner@example.com",
        sync_external=True,
        event_sink=sink,
    )
    assert str(customer.external_customer_id).startswith("stripe_customer_")
    await gateway.aclose()


def test_stripe_webhook_verifier_accepts_valid_signature() -> None:
    payload = '{"id":"evt_1","type":"invoice.paid","created":100,"data":{"object":{"id":"in_1"}}}'
    verifier = StripeWebhookVerifier("whsec_test", tolerance_seconds=300, clock=lambda: 100.0)
    header = build_stripe_signature_header(payload, "whsec_test", timestamp=100)

    event = verifier.verify(payload, header)

    assert event.event_id == "evt_1"
    assert event.event_type == "invoice.paid"
