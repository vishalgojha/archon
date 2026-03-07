"""Tests for marketplace revenue share accounting and payout queueing."""

from __future__ import annotations

from pathlib import Path

import pytest

from archon.marketplace.connect import CONNECT_ACCOUNT_METADATA_KEY
from archon.marketplace.revenue_share import SHARE_RATES, PayoutQueue, RevenueShareLedger
from archon.partners.registry import PartnerRegistry


class _RecordingGate:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def check(self, action: str, context: dict[str, object], action_id: str) -> str:
        self.calls.append({"action": action, "context": dict(context), "action_id": action_id})
        return action_id


class _StripeTransfers:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.calls: list[dict[str, object]] = []
        self.attempts = 0

    async def create_transfer(
        self,
        destination_account_id: str,
        amount_usd: float,
        *,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.attempts += 1
        self.calls.append(
            {
                "destination_account_id": destination_account_id,
                "amount_usd": amount_usd,
                "metadata": dict(metadata or {}),
            }
        )
        if self.fail_first and self.attempts == 1:
            raise RuntimeError("stripe temporarily unavailable")
        return {"id": f"tr_{self.attempts}"}


def _setup_partner_and_ledger(
    tmp_path: Path,
    *,
    price_tier: str = "pro_only",
    gross_events: list[float] | None = None,
) -> tuple[PartnerRegistry, RevenueShareLedger, str]:
    registry = PartnerRegistry(path=tmp_path / "partners.sqlite3")
    ledger = RevenueShareLedger(registry=registry, path=tmp_path / "marketplace.sqlite3")
    partner = registry.register("Revenue Partner", "partner@example.com", "affiliate")
    registry.update_metadata(partner.partner_id, {CONNECT_ACCOUNT_METADATA_KEY: "acct_partner_1"})
    ledger.upsert_listing("listing-1", partner.partner_id, price_tier)
    for amount in gross_events or []:
        ledger.record("tenant-1", "listing-1", amount)
    return registry, ledger, partner.partner_id


@pytest.mark.parametrize(
    ("price_tier", "expected_developer"),
    [
        ("free", 0.0),
        ("pro_only", 0.7),
        ("enterprise_only", 0.8),
    ],
)
def test_share_rates_match_expected_values(price_tier: str, expected_developer: float) -> None:
    assert SHARE_RATES[price_tier]["developer"] == expected_developer


@pytest.mark.parametrize(
    ("price_tier", "expected_developer_share"),
    [
        ("free", 0.0),
        ("pro_only", 70.0),
        ("enterprise_only", 80.0),
    ],
)
def test_record_splits_revenue_correctly_for_each_tier(
    tmp_path: Path,
    price_tier: str,
    expected_developer_share: float,
) -> None:
    registry, ledger, _partner_id = _setup_partner_and_ledger(tmp_path, price_tier=price_tier)
    del registry

    event = ledger.record("tenant-1", "listing-1", 100.0)

    assert round(event.developer_share_usd, 2) == expected_developer_share
    assert round(event.archon_share_usd, 2) == round(100.0 - expected_developer_share, 2)


def test_aggregate_developer_sums_multiple_events_correctly(tmp_path: Path) -> None:
    _registry, ledger, partner_id = _setup_partner_and_ledger(
        tmp_path,
        price_tier="pro_only",
        gross_events=[100.0, 50.0],
    )

    earnings = ledger.aggregate_developer(partner_id, 0.0, 9999999999.0)

    assert earnings.gross_usd == 150.0
    assert earnings.developer_usd == 105.0
    assert earnings.archon_usd == 45.0
    assert earnings.event_count == 2


def test_aggregate_archon_matches_gross_minus_developer_payouts(tmp_path: Path) -> None:
    _registry, ledger, _partner_id = _setup_partner_and_ledger(
        tmp_path,
        price_tier="enterprise_only",
        gross_events=[100.0, 50.0],
    )

    totals = ledger.aggregate_archon(0.0, 9999999999.0)

    assert totals.gross_usd == 150.0
    assert totals.developer_payouts_usd == 120.0
    assert totals.archon_net_usd == 30.0


def test_payout_queue_enqueue_returns_none_below_threshold(tmp_path: Path) -> None:
    registry, ledger, partner_id = _setup_partner_and_ledger(
        tmp_path,
        price_tier="pro_only",
        gross_events=[10.0],
    )
    queue = PayoutQueue(
        registry=registry,
        ledger=ledger,
        path=tmp_path / "marketplace.sqlite3",
        approval_gate=_RecordingGate(),  # type: ignore[arg-type]
    )

    payout = queue.enqueue(partner_id, 0.0, 9999999999.0)

    assert payout is None


@pytest.mark.asyncio
async def test_payout_queue_approve_uses_financial_transaction_gate(tmp_path: Path) -> None:
    registry, ledger, partner_id = _setup_partner_and_ledger(
        tmp_path,
        price_tier="pro_only",
        gross_events=[100.0],
    )
    gate = _RecordingGate()
    queue = PayoutQueue(
        registry=registry,
        ledger=ledger,
        path=tmp_path / "marketplace.sqlite3",
        approval_gate=gate,  # type: ignore[arg-type]
    )
    payout = queue.enqueue(partner_id, 0.0, 9999999999.0)
    assert payout is not None

    approved = await queue.approve(payout.payout_id)

    assert gate.calls
    assert gate.calls[0]["action"] == "financial_transaction"
    assert approved.status == "approved"


@pytest.mark.asyncio
async def test_payout_queue_execute_posts_transfer_and_marks_paid(tmp_path: Path) -> None:
    registry, ledger, partner_id = _setup_partner_and_ledger(
        tmp_path,
        price_tier="enterprise_only",
        gross_events=[20.0],
    )
    stripe = _StripeTransfers()
    queue = PayoutQueue(
        registry=registry,
        ledger=ledger,
        path=tmp_path / "marketplace.sqlite3",
        approval_gate=_RecordingGate(),  # type: ignore[arg-type]
        stripe_client=stripe,  # type: ignore[arg-type]
    )
    payout = queue.enqueue(partner_id, 0.0, 9999999999.0)
    assert payout is not None
    await queue.approve(payout.payout_id)

    result = await queue.execute(payout.payout_id)
    stored = queue.get(payout.payout_id)

    assert stripe.calls
    assert stripe.calls[0]["destination_account_id"] == "acct_partner_1"
    assert result.status == "paid"
    assert stored is not None
    assert stored.status == "paid"
    assert stored.transfer_id == "tr_1"


@pytest.mark.asyncio
async def test_failed_payout_retry_reexecutes_and_updates_status(tmp_path: Path) -> None:
    registry, ledger, partner_id = _setup_partner_and_ledger(
        tmp_path,
        price_tier="enterprise_only",
        gross_events=[20.0],
    )
    stripe = _StripeTransfers(fail_first=True)
    queue = PayoutQueue(
        registry=registry,
        ledger=ledger,
        path=tmp_path / "marketplace.sqlite3",
        approval_gate=_RecordingGate(),  # type: ignore[arg-type]
        stripe_client=stripe,  # type: ignore[arg-type]
    )
    payout = queue.enqueue(partner_id, 0.0, 9999999999.0)
    assert payout is not None
    await queue.approve(payout.payout_id)

    first = await queue.execute(payout.payout_id)
    retried = await queue.retry_failed(payout.payout_id)
    stored = queue.get(payout.payout_id)

    assert first.status == "failed"
    assert retried.status == "paid"
    assert stripe.attempts == 2
    assert stored is not None
    assert stored.status == "paid"
