"""Tests for payout orchestration, developer dashboard auth, reports, and CLI surfaces."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from archon.archon_cli import cli
from archon.interfaces.api.server import app
from archon.marketplace.connect import CONNECT_ACCOUNT_METADATA_KEY
from archon.marketplace.payout_orchestrator import PartnerRevenueReport, PayoutOrchestrator
from archon.marketplace.revenue_share import (
    DeveloperEarnings,
    PayoutQueue,
    Pending,
    RevenueShareLedger,
)
from archon.partners.registry import PartnerRegistry


def _auth_headers(*, tenant: str = "tenant-test", tier: str = "business") -> dict[str, str]:
    token = jwt.encode(
        {"sub": tenant, "tier": tier},
        "archon-dev-secret-change-me-32-bytes",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def _marketplace_envs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")
    monkeypatch.setenv("ARCHON_PARTNERS_DB", str(tmp_path / "partners.sqlite3"))
    monkeypatch.setenv(
        "ARCHON_MARKETPLACE_CONNECT_DB",
        str(tmp_path / "marketplace-connect.sqlite3"),
    )
    monkeypatch.setenv(
        "ARCHON_MARKETPLACE_REVENUE_DB",
        str(tmp_path / "marketplace-revenue.sqlite3"),
    )
    monkeypatch.setenv(
        "ARCHON_MARKETPLACE_CYCLE_DB",
        str(tmp_path / "marketplace-cycles.sqlite3"),
    )


class _RecordingGate:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def check(self, action: str, context: dict[str, object], action_id: str) -> str:
        self.calls.append({"action": action, "context": dict(context), "action_id": action_id})
        return action_id


class _StripeStub:
    def __init__(self, *, fail_first_for: set[str] | None = None) -> None:
        self.fail_first_for = set(fail_first_for or set())
        self.calls: list[dict[str, object]] = []
        self._attempts: dict[str, int] = {}

    async def create_transfer(
        self,
        destination_account_id: str,
        amount_usd: float,
        *,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        attempts = self._attempts.get(destination_account_id, 0) + 1
        self._attempts[destination_account_id] = attempts
        self.calls.append(
            {
                "destination_account_id": destination_account_id,
                "amount_usd": amount_usd,
                "metadata": dict(metadata or {}),
            }
        )
        if destination_account_id in self.fail_first_for and attempts == 1:
            raise RuntimeError(f"transfer failed for {destination_account_id}")
        return {"id": f"tr_{destination_account_id}_{attempts}"}


def _build_runtime(
    tmp_path: Path,
    *,
    gate: _RecordingGate | None = None,
    stripe: _StripeStub | None = None,
) -> tuple[PartnerRegistry, RevenueShareLedger, PayoutQueue, PayoutOrchestrator]:
    registry = PartnerRegistry(path=tmp_path / "partners.sqlite3")
    ledger = RevenueShareLedger(registry=registry, path=tmp_path / "marketplace.sqlite3")
    queue = PayoutQueue(
        registry=registry,
        ledger=ledger,
        path=tmp_path / "marketplace.sqlite3",
        approval_gate=gate or _RecordingGate(),  # type: ignore[arg-type]
        stripe_client=stripe,  # type: ignore[arg-type]
    )
    orchestrator = PayoutOrchestrator(
        registry=registry,
        ledger=ledger,
        payout_queue=queue,
        approval_gate=queue.approval_gate,
        path=tmp_path / "cycles.sqlite3",
    )
    return registry, ledger, queue, orchestrator


def _activate_partner(
    registry: PartnerRegistry,
    ledger: RevenueShareLedger,
    *,
    name: str,
    email: str,
    account_id: str,
    listing_id: str,
    price_tier: str,
    gross_events: list[float],
) -> str:
    partner = registry.register(name, email, "affiliate")
    registry.update_metadata(partner.partner_id, {CONNECT_ACCOUNT_METADATA_KEY: account_id})
    registry.update_status(partner.partner_id, "active", "activated-for-test")
    ledger.upsert_listing(listing_id, partner.partner_id, price_tier)
    for amount in gross_events:
        ledger.record("tenant-1", listing_id, amount)
    return partner.partner_id


@pytest.mark.asyncio
async def test_run_cycle_skips_below_threshold_and_enqueues_eligible(tmp_path: Path) -> None:
    gate = _RecordingGate()
    stripe = _StripeStub()
    registry, ledger, queue, orchestrator = _build_runtime(tmp_path, gate=gate, stripe=stripe)
    _activate_partner(
        registry,
        ledger,
        name="Partner A",
        email="a@example.com",
        account_id="acct_a",
        listing_id="listing-a",
        price_tier="pro_only",
        gross_events=[100.0],
    )
    _activate_partner(
        registry,
        ledger,
        name="Partner B",
        email="b@example.com",
        account_id="acct_b",
        listing_id="listing-b",
        price_tier="pro_only",
        gross_events=[10.0],
    )

    result = await orchestrator.run_cycle(0.0, 9999999999.0)

    assert result.partners_paid == 1
    assert result.partners_skipped == 1
    assert len(queue.list_payouts(status_filter="paid")) == 1


@pytest.mark.asyncio
async def test_run_cycle_uses_single_batch_approval_call(tmp_path: Path) -> None:
    gate = _RecordingGate()
    stripe = _StripeStub()
    registry, ledger, _queue, orchestrator = _build_runtime(tmp_path, gate=gate, stripe=stripe)
    _activate_partner(
        registry,
        ledger,
        name="Partner A",
        email="a@example.com",
        account_id="acct_a",
        listing_id="listing-a",
        price_tier="pro_only",
        gross_events=[100.0],
    )
    _activate_partner(
        registry,
        ledger,
        name="Partner B",
        email="b@example.com",
        account_id="acct_b",
        listing_id="listing-b",
        price_tier="enterprise_only",
        gross_events=[20.0],
    )

    await orchestrator.run_cycle(0.0, 9999999999.0)

    assert len(gate.calls) == 1
    assert gate.calls[0]["action"] == "financial_transaction"


@pytest.mark.asyncio
async def test_run_cycle_executes_eligible_payouts_with_asyncio_gather(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _RecordingGate()
    stripe = _StripeStub()
    registry, ledger, _queue, orchestrator = _build_runtime(tmp_path, gate=gate, stripe=stripe)
    _activate_partner(
        registry,
        ledger,
        name="Partner A",
        email="a@example.com",
        account_id="acct_a",
        listing_id="listing-a",
        price_tier="pro_only",
        gross_events=[100.0],
    )
    _activate_partner(
        registry,
        ledger,
        name="Partner B",
        email="b@example.com",
        account_id="acct_b",
        listing_id="listing-b",
        price_tier="enterprise_only",
        gross_events=[20.0],
    )
    real_gather = asyncio.gather
    calls: dict[str, int] = {}

    async def fake_gather(*aws):  # type: ignore[no-untyped-def]
        calls["count"] = len(aws)
        return await real_gather(*aws)

    monkeypatch.setattr("archon.marketplace.payout_orchestrator.asyncio.gather", fake_gather)

    await orchestrator.run_cycle(0.0, 9999999999.0)

    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_run_cycle_totals_match_sum_of_paid_payouts(tmp_path: Path) -> None:
    gate = _RecordingGate()
    stripe = _StripeStub()
    registry, ledger, queue, orchestrator = _build_runtime(tmp_path, gate=gate, stripe=stripe)
    _activate_partner(
        registry,
        ledger,
        name="Partner A",
        email="a@example.com",
        account_id="acct_a",
        listing_id="listing-a",
        price_tier="pro_only",
        gross_events=[100.0],
    )
    _activate_partner(
        registry,
        ledger,
        name="Partner B",
        email="b@example.com",
        account_id="acct_b",
        listing_id="listing-b",
        price_tier="enterprise_only",
        gross_events=[20.0],
    )

    result = await orchestrator.run_cycle(0.0, 9999999999.0)
    paid_total = sum(row.amount_usd for row in queue.list_payouts(status_filter="paid"))

    assert result.total_paid_usd == paid_total


@pytest.mark.asyncio
async def test_retry_failures_only_retries_failed_payouts(tmp_path: Path) -> None:
    gate = _RecordingGate()
    stripe = _StripeStub(fail_first_for={"acct_b"})
    registry, ledger, queue, orchestrator = _build_runtime(tmp_path, gate=gate, stripe=stripe)
    _activate_partner(
        registry,
        ledger,
        name="Partner A",
        email="a@example.com",
        account_id="acct_a",
        listing_id="listing-a",
        price_tier="pro_only",
        gross_events=[100.0],
    )
    _activate_partner(
        registry,
        ledger,
        name="Partner B",
        email="b@example.com",
        account_id="acct_b",
        listing_id="listing-b",
        price_tier="enterprise_only",
        gross_events=[20.0],
    )
    cycle = await orchestrator.run_cycle(0.0, 9999999999.0)
    retried: list[str] = []
    original_retry_failed = queue.retry_failed

    async def tracking_retry_failed(payout_id: str):  # type: ignore[no-untyped-def]
        retried.append(payout_id)
        return await original_retry_failed(payout_id)

    queue.retry_failed = tracking_retry_failed  # type: ignore[assignment]

    await orchestrator.retry_failures(cycle.cycle_id)

    assert len(cycle.failures) == 1
    assert retried == cycle.failures


def test_developer_dashboard_blocks_partner_from_other_partner_earnings(
    _marketplace_envs: None,
) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/marketplace/developers/partner-b/earnings",
            headers=_auth_headers(tenant="partner-a", tier="business"),
        )

    assert response.status_code == 401


def test_enterprise_tier_can_access_marketplace_revenue_summary(
    _marketplace_envs: None,
) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/marketplace/revenue/summary",
            headers=_auth_headers(tenant="tenant-enterprise", tier="enterprise"),
        )

    assert response.status_code == 200
    assert "gross_usd" in response.json()


def test_free_tier_cannot_access_marketplace_revenue_summary(
    _marketplace_envs: None,
) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/marketplace/revenue/summary",
            headers=_auth_headers(tenant="tenant-free", tier="free"),
        )

    assert response.status_code == 403


def test_partner_revenue_report_listing_breakdown_sums_to_total_earnings(tmp_path: Path) -> None:
    registry, ledger, queue, _orchestrator = _build_runtime(tmp_path, stripe=_StripeStub())
    partner_id = _activate_partner(
        registry,
        ledger,
        name="Partner A",
        email="a@example.com",
        account_id="acct_a",
        listing_id="listing-a",
        price_tier="pro_only",
        gross_events=[100.0],
    )
    ledger.upsert_listing("listing-b", partner_id, "enterprise_only")
    ledger.record("tenant-1", "listing-b", 50.0)
    report = PartnerRevenueReport(ledger=ledger, payout_queue=queue).generate(
        partner_id,
        0.0,
        9999999999.0,
    )

    assert (
        sum(row["developer_usd"] for row in report.listing_breakdown)
        == report.earnings.developer_usd
    )


def test_partner_revenue_report_trend_can_be_positive_or_negative(tmp_path: Path) -> None:
    registry, ledger, queue, _orchestrator = _build_runtime(tmp_path, stripe=_StripeStub())
    partner_id = _activate_partner(
        registry,
        ledger,
        name="Partner A",
        email="a@example.com",
        account_id="acct_a",
        listing_id="listing-a",
        price_tier="pro_only",
        gross_events=[],
    )
    prior_positive = ledger.record("tenant-1", "listing-a", 10.0)
    current_positive = ledger.record("tenant-1", "listing-a", 40.0)
    prior_negative = ledger.record("tenant-1", "listing-a", 60.0)
    current_negative = ledger.record("tenant-1", "listing-a", 10.0)
    with sqlite3.connect(tmp_path / "marketplace.sqlite3") as conn:
        conn.execute(
            "UPDATE marketplace_revenue_events SET timestamp = ? WHERE event_id = ?",
            (50.0, prior_positive.event_id),
        )
        conn.execute(
            "UPDATE marketplace_revenue_events SET timestamp = ? WHERE event_id = ?",
            (150.0, current_positive.event_id),
        )
        conn.execute(
            "UPDATE marketplace_revenue_events SET timestamp = ? WHERE event_id = ?",
            (250.0, prior_negative.event_id),
        )
        conn.execute(
            "UPDATE marketplace_revenue_events SET timestamp = ? WHERE event_id = ?",
            (350.0, current_negative.event_id),
        )

    positive = PartnerRevenueReport(ledger=ledger, payout_queue=queue).generate(
        partner_id,
        100.0,
        200.0,
    )
    negative = PartnerRevenueReport(ledger=ledger, payout_queue=queue).generate(
        partner_id,
        300.0,
        400.0,
    )

    assert positive.trend_vs_prior_period > 0.0
    assert negative.trend_vs_prior_period < 0.0


def test_cli_payouts_list_outputs_payout_id_and_amount(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRegistry:
        def get(self, partner_id: str):  # type: ignore[no-untyped-def]
            return SimpleNamespace(name=f"Partner {partner_id}")

    class FakeQueue:
        def list_pending(self):  # type: ignore[no-untyped-def]
            return [
                Pending(
                    payout_id="payout-123",
                    partner_id="partner-1",
                    account_id="acct_1",
                    amount_usd=42.5,
                    period_start=0.0,
                    period_end=1.0,
                    status="pending",
                    created_at=1.0,
                )
            ]

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(
        "archon.archon_cli._marketplace_runtime",
        lambda: (FakeRegistry(), object(), FakeQueue(), object()),
    )

    result = CliRunner().invoke(cli, ["payouts", "list"])

    assert result.exit_code == 0
    assert "payout-123" in result.output
    assert "$42.50" in result.output


def test_cli_earnings_outputs_partner_id_and_total(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeQueue:
        async def aclose(self) -> None:
            return None

    class FakeLedger:
        def aggregate_developer(
            self, partner_id: str, period_start: float, period_end: float
        ) -> DeveloperEarnings:
            assert period_start < period_end
            return DeveloperEarnings(
                partner_id=partner_id,
                gross_usd=100.0,
                developer_usd=70.0,
                archon_usd=30.0,
                event_count=1,
                period_start=period_start,
                period_end=period_end,
            )

    monkeypatch.setattr(
        "archon.archon_cli._marketplace_runtime",
        lambda: (object(), FakeLedger(), FakeQueue(), object()),
    )

    result = CliRunner().invoke(cli, ["earnings", "partner-1", "--period", "2026-03"])

    assert result.exit_code == 0
    assert "partner-1" in result.output
    assert "$70.00" in result.output
