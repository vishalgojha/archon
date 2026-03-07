"""Tests for billing pricing, approval gating, and webhook verification."""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from archon.billing import (
    BillingInvoice,
    BillingService,
    BillingStore,
    BillingSubscription,
    InvoiceGenerator,
    StripeClient,
    StripeGateway,
    StripeWebhookHandler,
    StripeWebhookVerifier,
    UsageMeter,
)
from archon.billing.invoices import METRIC_PRICES
from archon.billing.metering import SUPPORTED_METRICS
from archon.billing.models import SubscriptionChange
from archon.billing.stripe_client import UsageRecord as StripeUsageRecord
from archon.billing.webhooks import build_stripe_signature_header
from archon.core.approval_gate import ApprovalRequiredError


def _tmp_db(name: str) -> Path:
    root = Path("archon/tests/_tmp_billing")
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{name}-{uuid.uuid4().hex[:8]}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "billing.sqlite3"


def _tmp_dir(name: str) -> Path:
    root = Path("archon/tests/_tmp_billing")
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{name}-{uuid.uuid4().hex[:8]}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


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


class _MockResponse:
    def __init__(self, payload: dict[str, object], *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _MockStripeHttpClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, object]]] = []
        self.gets: list[tuple[str, dict[str, object]]] = []

    async def post(self, url: str, *, headers: dict[str, str], data: dict[str, object]):  # type: ignore[no-untyped-def]
        del headers
        self.posts.append((url, dict(data)))
        if url.endswith("/customers"):
            return _MockResponse(
                {
                    "id": "cus_123",
                    "email": data.get("email", ""),
                    "metadata": {"tenant_id": data.get("metadata[tenant_id]", "")},
                }
            )
        if "/subscription_items/" in url:
            subscription_item_id = url.rsplit("/", 2)[1]
            return _MockResponse(
                {
                    "id": "ur_123",
                    "subscription_item": subscription_item_id,
                    "quantity": data.get("quantity", 0.0),
                    "timestamp": data.get("timestamp", 0),
                }
            )
        if url.endswith("/subscriptions"):
            return _MockResponse({"id": "sub_123", "status": "active", "current_period_end": 100.0})
        return _MockResponse({})

    async def get(self, url: str, *, headers: dict[str, str], params: dict[str, object]):  # type: ignore[no-untyped-def]
        del headers
        self.gets.append((url, dict(params)))
        return _MockResponse(
            {
                "data": [
                    {
                        "id": "in_1",
                        "amount_due": 5000,
                        "currency": "usd",
                        "status": "paid",
                        "invoice_pdf": "https://stripe.test/in_1.pdf",
                        "period_start": 10,
                        "period_end": 20,
                    },
                    {
                        "id": "in_2",
                        "amount_due": 2500,
                        "currency": "usd",
                        "status": "open",
                        "invoice_pdf": "",
                        "period_start": 21,
                        "period_end": 30,
                    },
                ]
            }
        )


@pytest.mark.asyncio
async def test_stripe_client_create_customer_posts_correct_form_data_and_list_invoices() -> None:
    http_client = _MockStripeHttpClient()
    client = StripeClient(
        secret_key="sk_test_123", webhook_secret="whsec_test", http_client=http_client
    )  # type: ignore[arg-type]

    customer = await client.create_customer("tenant-a", "owner@example.com", "Owner")
    invoices = await client.list_invoices("cus_123", limit=2)

    assert customer.customer_id == "cus_123"
    assert http_client.posts[0][0].endswith("/customers")
    assert http_client.posts[0][1]["metadata[tenant_id]"] == "tenant-a"
    assert http_client.posts[0][1]["email"] == "owner@example.com"
    assert len(invoices) == 2
    assert http_client.gets[0][1]["limit"] == 2


def test_stripe_client_construct_webhook_event_accepts_valid_signature_and_rejects_invalid() -> (
    None
):
    payload = (
        b'{"id":"evt_42","type":"invoice.paid","created":100,"data":{"object":{"id":"in_42"}}}'
    )
    client = StripeClient(secret_key="sk_test_123", webhook_secret="whsec_test")
    valid = build_stripe_signature_header(
        payload.decode("utf-8"), "whsec_test", timestamp=int(__import__("time").time())
    )

    event = client.construct_webhook_event(payload, valid)

    assert event.event_id == "evt_42"
    assert event.event_type == "invoice.paid"
    with pytest.raises(ValueError):
        client.construct_webhook_event(payload, "t=100,v1=bad")


def test_usage_meter_record_and_aggregate_sum_period_totals() -> None:
    meter = UsageMeter(path=_tmp_db("meter"))

    first = meter.record("tenant-a", "agent_runs", 2.0, {"task_id": "task-1"})
    second = meter.record("tenant-a", "agent_runs", 3.0, {"task_id": "task-2"})
    total = meter.aggregate("tenant-a", "agent_runs", first.timestamp - 1, second.timestamp + 1)

    assert first.event_id != second.event_id
    assert total == 5.0


@pytest.mark.asyncio
async def test_usage_meter_flush_to_stripe_calls_gate_before_posting_and_flushes_multiple_metrics() -> (
    None
):
    order: list[str] = []

    class _Gate:
        async def check(self, action: str, context: dict[str, object], action_id: str) -> str:
            assert action == "financial_transaction"
            assert "aggregates" in context
            order.append("gate")
            return action_id

    class _Stripe:
        async def create_usage_record(
            self, subscription_item_id: str, quantity: float, timestamp: float
        ) -> StripeUsageRecord:
            order.append(subscription_item_id)
            return StripeUsageRecord(
                record_id=f"ur_{subscription_item_id}",
                subscription_item_id=subscription_item_id,
                quantity=quantity,
                timestamp=timestamp,
            )

    meter = UsageMeter(path=_tmp_db("meter-flush"), approval_gate=_Gate(), stripe_client=_Stripe())  # type: ignore[arg-type]
    meter.record("tenant-a", "agent_runs", 2.0, {})
    meter.record("tenant-a", "emails_sent", 1.0, {})

    records = await meter.flush_to_stripe("tenant-a", 0.0, time.time() + 1)

    assert len(records) == 2
    assert order[0] == "gate"
    assert set(order[1:]) == {"si_agent_runs", "si_emails_sent"}


def test_invoice_generator_line_items_subtotal_tax_and_export_json() -> None:
    meter = UsageMeter(path=_tmp_db("invoice-generator"))
    meter.record("tenant-a", "tokens_input", 1000.0, {})
    meter.record("tenant-a", "agent_runs", 3.0, {})
    generator = InvoiceGenerator(meter, tier_lookup=lambda tenant_id: "pro", tax_rate=0.1)

    invoice = generator.generate("tenant-a", 0.0, time.time() + 1)
    output_path = generator.export_json(invoice, _tmp_dir("invoice-export") / "invoice.jsonl")

    expected_input = 1000.0 * METRIC_PRICES["tokens_input"]["pro"]
    expected_runs = 3.0 * METRIC_PRICES["agent_runs"]["pro"]
    assert len(invoice.line_items) == 2
    assert invoice.subtotal_usd == round(expected_input + expected_runs, 6)
    assert invoice.tax_usd == round(invoice.subtotal_usd * 0.1, 6)
    lines = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines[0]["type"] == "invoice"
    assert lines[1]["type"] == "line_item"


@pytest.mark.asyncio
async def test_stripe_webhook_handler_invoice_paid_updates_status_and_subscription_deleted_downgrades() -> (
    None
):
    store = BillingStore(path=_tmp_db("webhook-handler"))
    service = BillingService(store=store)
    store.upsert_subscription(
        BillingSubscription(
            tenant_id="tenant-a",
            plan_id="growth",
            period_start=0.0,
            period_end=100.0,
            created_at=0.0,
            updated_at=0.0,
        )
    )
    store.save_invoice(
        BillingInvoice(
            tenant_id="tenant-a",
            plan_id="growth",
            subscription_id="sub_local",
            period_start=0.0,
            period_end=100.0,
            lines=[],
            status="draft",
            external_invoice_id="in_123",
        )
    )
    handler = StripeWebhookHandler(
        billing_service=service,
        stripe_client=StripeClient(secret_key="sk_test", webhook_secret="whsec_test"),
    )

    now = int(__import__("time").time())
    invoice_payload = json.dumps(
        {
            "id": "evt_paid",
            "type": "invoice.paid",
            "created": now,
            "data": {"object": {"id": "in_123", "metadata": {"tenant_id": "tenant-a"}}},
        }
    )
    deleted_payload = json.dumps(
        {
            "id": "evt_deleted",
            "type": "customer.subscription.deleted",
            "created": now,
            "data": {"object": {"id": "sub_123", "metadata": {"tenant_id": "tenant-a"}}},
        }
    )
    await handler.handle(
        invoice_payload.encode("utf-8"),
        build_stripe_signature_header(invoice_payload, "whsec_test", timestamp=now),
    )
    await handler.handle(
        deleted_payload.encode("utf-8"),
        build_stripe_signature_header(deleted_payload, "whsec_test", timestamp=now),
    )

    assert store.find_invoice_by_external_id("in_123").status == "paid"  # type: ignore[union-attr]
    assert store.get_subscription("tenant-a").plan_id == "free"  # type: ignore[union-attr]


def test_stripe_webhook_handler_invalid_signature_returns_400() -> None:
    app = FastAPI()
    app.include_router(
        StripeWebhookHandler(
            stripe_client=StripeClient(secret_key="sk_test", webhook_secret="whsec_test")
        ).router()
    )
    with TestClient(app) as client:
        response = client.post(
            "/billing/webhooks/stripe",
            data='{"id":"evt_1","type":"invoice.paid","data":{"object":{"id":"in_1"}}}',
            headers={"Stripe-Signature": "t=1,v1=invalid"},
        )

    assert response.status_code == 400


@pytest.mark.parametrize("metric", SUPPORTED_METRICS)
def test_usage_meter_metric_roundtrip_matrix(metric: str) -> None:
    meter = UsageMeter(path=_tmp_db(f"meter-{metric}"))

    event = meter.record("tenant-matrix", metric, 2.0, {"metric": metric})
    total = meter.aggregate("tenant-matrix", metric, event.timestamp - 1, event.timestamp + 1)
    stored = meter.list_events("tenant-matrix", metric=metric)

    assert total == 2.0
    assert len(stored) == 1
    assert stored[0].metadata["metric"] == metric


@pytest.mark.parametrize(
    ("metric", "tier", "quantity"),
    [
        (metric, tier, quantity)
        for metric in SUPPORTED_METRICS
        for tier in ("free", "pro", "enterprise")
        for quantity in (0.5, 1.0, 3.0, 10.0)
    ],
)
def test_invoice_generator_metric_price_matrix(metric: str, tier: str, quantity: float) -> None:
    meter = UsageMeter(path=_tmp_db(f"invoice-matrix-{metric}-{tier}-{quantity}"))
    meter.record("tenant-matrix", metric, quantity, {})
    generator = InvoiceGenerator(meter, tier_lookup=lambda tenant_id: tier, tax_rate=0.0)

    invoice = generator.generate("tenant-matrix", 0.0, time.time() + 1)

    assert len(invoice.line_items) == 1
    assert invoice.line_items[0].description == metric.replace("_", " ").title()
    assert invoice.line_items[0].quantity == quantity
    assert invoice.line_items[0].unit_price_usd == METRIC_PRICES[metric][tier]
    assert invoice.subtotal_usd == round(quantity * METRIC_PRICES[metric][tier], 6)
