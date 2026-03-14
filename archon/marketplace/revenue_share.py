"""Marketplace revenue attribution, payout queueing, and Stripe transfers."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from archon.compliance.encryption import EncryptionLayer
from archon.compliance.retention import RetentionRule
from archon.core.approval_gate import ApprovalGate, EventSink
from archon.marketplace.connect import StripeConnectClient, decrypt_partner_account_id
from archon.partners.registry import Partner, PartnerRegistry

PRICE_TIERS: tuple[str, ...] = ("free", "pro_only", "enterprise_only")
PAYOUT_STATUSES: tuple[str, ...] = ("pending", "approved", "paid", "failed")
SHARE_RATES: dict[str, dict[str, float]] = {
    "free": {"developer": 0.0, "archon": 1.0},
    "pro_only": {"developer": 0.7, "archon": 0.3},
    "enterprise_only": {"developer": 0.8, "archon": 0.2},
}

MARKETPLACE_LISTING_RETENTION_RULE = RetentionRule(
    entity_type="marketplace_listing",
    retention_days=3650,
    action="archive",
)
REVENUE_EVENT_RETENTION_RULE = RetentionRule(
    entity_type="marketplace_revenue_event",
    retention_days=3650,
    action="archive",
)
PAYOUT_RECORD_RETENTION_RULE = RetentionRule(
    entity_type="marketplace_payout_record",
    retention_days=3650,
    action="archive",
)


def _now() -> float:
    return time.time()


def _round_usd(value: float) -> float:
    return round(float(value or 0.0) + 1e-9, 2)


def _revenue_event_id() -> str:
    return f"mrev-{uuid.uuid4().hex[:12]}"


def _payout_id() -> str:
    return f"payout-{uuid.uuid4().hex[:12]}"


def _default_master_key() -> bytes:
    env = str(os.getenv("ARCHON_MASTER_KEY", "")).strip()
    if env:
        try:
            return EncryptionLayer.master_key_from_env()
        except ValueError:
            pass
    return b"d" * 32


def _period_label(timestamp: float) -> str:
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).strftime("%Y-%m")


def _json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _encrypt_account(partner_id: str, account_id: str, master_key: bytes) -> str:
    payload = EncryptionLayer.encrypt(
        str(account_id or ""),
        EncryptionLayer.derive_key(str(partner_id), master_key),
    )
    return _json_dumps(asdict(payload))


def _decrypt_account(partner_id: str, payload: str, master_key: bytes) -> str:
    return EncryptionLayer.decrypt(
        json.loads(str(payload or "{}")),
        EncryptionLayer.derive_key(str(partner_id), master_key),
    )


@dataclass(slots=True, frozen=True)
class ListingRecord:
    """One marketplace listing mapping row.

    Example:
        >>> ListingRecord("listing-1", "partner-1", "pro_only").price_tier
        'pro_only'
    """

    listing_id: str
    partner_id: str
    price_tier: str
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)


@dataclass(slots=True, frozen=True)
class RevenueEvent:
    """One append-only marketplace revenue event.

    Example:
        >>> RevenueEvent("evt", "tenant", "listing", "partner", 10.0, 3.0, 7.0, 1.0, "2026-03").event_id
        'evt'
    """

    event_id: str
    tenant_id: str
    listing_id: str
    partner_id: str
    gross_usd: float
    archon_share_usd: float
    developer_share_usd: float
    timestamp: float
    billing_period: str


@dataclass(slots=True, frozen=True)
class DeveloperEarnings:
    """Aggregated developer earnings for one time window.

    Example:
        >>> DeveloperEarnings("partner-1", 100.0, 70.0, 30.0, 1, 0.0, 10.0).developer_usd
        70.0
    """

    partner_id: str
    gross_usd: float
    developer_usd: float
    archon_usd: float
    event_count: int
    period_start: float
    period_end: float


@dataclass(slots=True, frozen=True)
class ArchonEarnings:
    """Aggregated ARCHON marketplace earnings for one time window.

    Example:
        >>> ArchonEarnings(100.0, 70.0, 30.0, 1).archon_net_usd
        30.0
    """

    gross_usd: float
    developer_payouts_usd: float
    archon_net_usd: float
    partner_count: int


@dataclass(slots=True, frozen=True)
class Pending:
    """One payout queue record.

    Example:
        >>> Pending("payout-1", "partner-1", "acct_1", 10.0, 0.0, 1.0, "pending", 1.0).status
        'pending'
    """

    payout_id: str
    partner_id: str
    account_id: str
    amount_usd: float
    period_start: float
    period_end: float
    status: str
    created_at: float
    transfer_id: str | None = None
    cycle_id: str | None = None
    updated_at: float | None = None
    error_text: str | None = None


@dataclass(slots=True, frozen=True)
class PayoutResult:
    """Result of one transfer execution.

    Example:
        >>> PayoutResult("payout-1", "tr_1", "paid", 1.0).status
        'paid'
    """

    payout_id: str
    transfer_id: str
    status: str
    executed_at: float


class RevenueShareLedger:
    """Append-only revenue ledger for marketplace listings.

    Example:
        >>> registry = PartnerRegistry(path=":memory:")
        >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
        >>> ledger.aggregate_archon(0.0, 1.0).gross_usd
        0.0
    """

    def __init__(
        self,
        registry: PartnerRegistry,
        *,
        path: str | Path = "archon_marketplace_revenue.sqlite3",
    ) -> None:
        self.registry = registry
        self.path = Path(path)
        self._init_db()

    def upsert_listing(self, listing_id: str, partner_id: str, price_tier: str) -> ListingRecord:
        """Create or update one listing-to-partner revenue mapping.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> partner = registry.register("P", "p@example.com", "affiliate")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> ledger.upsert_listing("listing-1", partner.partner_id, "free").listing_id
            'listing-1'
        """

        clean_listing_id = str(listing_id or "").strip()
        clean_partner_id = str(partner_id or "").strip()
        clean_tier = str(price_tier or "").strip().lower()
        if not clean_listing_id:
            raise ValueError("listing_id is required.")
        if not clean_partner_id:
            raise ValueError("partner_id is required.")
        if clean_tier not in PRICE_TIERS:
            raise ValueError(f"Invalid price_tier '{price_tier}'.")
        partner = self.registry.get(clean_partner_id)
        if partner is None:
            raise KeyError(f"Partner '{clean_partner_id}' not found.")

        existing = self.get_listing(clean_listing_id)
        created_at = existing.created_at if existing is not None else _now()
        updated_at = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO marketplace_listings(
                    listing_id,
                    partner_id,
                    price_tier,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(listing_id) DO UPDATE SET
                    partner_id = excluded.partner_id,
                    price_tier = excluded.price_tier,
                    updated_at = excluded.updated_at
                """,
                (clean_listing_id, clean_partner_id, clean_tier, created_at, updated_at),
            )
        return ListingRecord(
            listing_id=clean_listing_id,
            partner_id=clean_partner_id,
            price_tier=clean_tier,
            created_at=created_at,
            updated_at=updated_at,
        )

    def get_listing(self, listing_id: str) -> ListingRecord | None:
        """Load one listing mapping by id.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> ledger.get_listing("missing") is None
            True
        """

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT listing_id, partner_id, price_tier, created_at, updated_at
                FROM marketplace_listings
                WHERE listing_id = ?
                """,
                (str(listing_id or "").strip(),),
            ).fetchone()
        return self._to_listing(row)

    def record(self, tenant_id: str, listing_id: str, gross_usd: float) -> RevenueEvent:
        """Append one revenue event for a marketplace listing.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> partner = registry.register("P", "p@example.com", "affiliate")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> _ = ledger.upsert_listing("listing-1", partner.partner_id, "free")
            >>> ledger.record("tenant-1", "listing-1", 5.0).gross_usd
            5.0
        """

        clean_tenant_id = str(tenant_id or "").strip()
        clean_listing_id = str(listing_id or "").strip()
        if not clean_tenant_id:
            raise ValueError("tenant_id is required.")
        if not clean_listing_id:
            raise ValueError("listing_id is required.")
        amount = _round_usd(gross_usd)
        if amount < 0:
            raise ValueError("gross_usd must be >= 0.")

        listing = self.get_listing(clean_listing_id)
        if listing is None:
            raise KeyError(f"Listing '{clean_listing_id}' not found.")
        split = SHARE_RATES[listing.price_tier]
        developer_share = _round_usd(amount * split["developer"])
        archon_share = _round_usd(amount - developer_share)
        timestamp = _now()
        row = RevenueEvent(
            event_id=_revenue_event_id(),
            tenant_id=clean_tenant_id,
            listing_id=clean_listing_id,
            partner_id=listing.partner_id,
            gross_usd=amount,
            archon_share_usd=archon_share,
            developer_share_usd=developer_share,
            timestamp=timestamp,
            billing_period=_period_label(timestamp),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO marketplace_revenue_events(
                    event_id,
                    tenant_id,
                    listing_id,
                    partner_id,
                    gross_usd,
                    archon_share_usd,
                    developer_share_usd,
                    timestamp,
                    billing_period
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.event_id,
                    row.tenant_id,
                    row.listing_id,
                    row.partner_id,
                    row.gross_usd,
                    row.archon_share_usd,
                    row.developer_share_usd,
                    row.timestamp,
                    row.billing_period,
                ),
            )
        return row

    def aggregate_developer(
        self,
        partner_id: str,
        period_start: float,
        period_end: float,
    ) -> DeveloperEarnings:
        """Aggregate one developer's earnings for a time window.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> ledger.aggregate_developer("partner-1", 0.0, 1.0).event_count
            0
        """

        clean_partner_id = str(partner_id or "").strip()
        if not clean_partner_id:
            raise ValueError("partner_id is required.")
        start = float(period_start)
        end = float(period_end)
        if end < start:
            raise ValueError("period_end must be >= period_start.")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(gross_usd), 0.0) AS gross_total,
                    COALESCE(SUM(developer_share_usd), 0.0) AS developer_total,
                    COALESCE(SUM(archon_share_usd), 0.0) AS archon_total,
                    COUNT(*) AS event_count
                FROM marketplace_revenue_events
                WHERE partner_id = ?
                  AND timestamp >= ?
                  AND timestamp < ?
                """,
                (clean_partner_id, start, end),
            ).fetchone()
        return DeveloperEarnings(
            partner_id=clean_partner_id,
            gross_usd=_round_usd(float(row["gross_total"] if row else 0.0)),
            developer_usd=_round_usd(float(row["developer_total"] if row else 0.0)),
            archon_usd=_round_usd(float(row["archon_total"] if row else 0.0)),
            event_count=int(row["event_count"] if row else 0),
            period_start=start,
            period_end=end,
        )

    def aggregate_archon(self, period_start: float, period_end: float) -> ArchonEarnings:
        """Aggregate ARCHON net revenue for a time window.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> ledger.aggregate_archon(0.0, 1.0).partner_count
            0
        """

        start = float(period_start)
        end = float(period_end)
        if end < start:
            raise ValueError("period_end must be >= period_start.")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(gross_usd), 0.0) AS gross_total,
                    COALESCE(SUM(developer_share_usd), 0.0) AS developer_total,
                    COALESCE(SUM(archon_share_usd), 0.0) AS archon_total,
                    COUNT(DISTINCT partner_id) AS partner_count
                FROM marketplace_revenue_events
                WHERE timestamp >= ?
                  AND timestamp < ?
                """,
                (start, end),
            ).fetchone()
        return ArchonEarnings(
            gross_usd=_round_usd(float(row["gross_total"] if row else 0.0)),
            developer_payouts_usd=_round_usd(float(row["developer_total"] if row else 0.0)),
            archon_net_usd=_round_usd(float(row["archon_total"] if row else 0.0)),
            partner_count=int(row["partner_count"] if row else 0),
        )

    def listing_breakdown(
        self,
        partner_id: str,
        period_start: float,
        period_end: float,
    ) -> list[dict[str, Any]]:
        """Return per-listing revenue totals for one developer and time window.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> ledger.listing_breakdown("partner-1", 0.0, 1.0)
            []
        """

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    listing_id,
                    COALESCE(SUM(gross_usd), 0.0) AS gross_total,
                    COALESCE(SUM(developer_share_usd), 0.0) AS developer_total,
                    COALESCE(SUM(archon_share_usd), 0.0) AS archon_total,
                    COUNT(*) AS event_count
                FROM marketplace_revenue_events
                WHERE partner_id = ?
                  AND timestamp >= ?
                  AND timestamp < ?
                GROUP BY listing_id
                ORDER BY gross_total DESC, listing_id ASC
                """,
                (str(partner_id or "").strip(), float(period_start), float(period_end)),
            ).fetchall()
        return [
            {
                "listing_id": str(row["listing_id"]),
                "gross_usd": _round_usd(float(row["gross_total"])),
                "developer_usd": _round_usd(float(row["developer_total"])),
                "archon_usd": _round_usd(float(row["archon_total"])),
                "event_count": int(row["event_count"]),
            }
            for row in rows
        ]

    def prune(self, *, max_age_seconds: int) -> int:
        """Delete revenue events older than the given age threshold.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> ledger.prune(max_age_seconds=3600)
            0
        """

        if int(max_age_seconds) <= 0:
            raise ValueError("max_age_seconds must be > 0.")
        cutoff = _now() - float(max_age_seconds)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM marketplace_revenue_events WHERE timestamp < ?",
                (cutoff,),
            )
        return int(cursor.rowcount)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS marketplace_listings (
                    listing_id TEXT PRIMARY KEY,
                    partner_id TEXT NOT NULL,
                    price_tier TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS marketplace_revenue_events (
                    event_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    listing_id TEXT NOT NULL,
                    partner_id TEXT NOT NULL,
                    gross_usd REAL NOT NULL,
                    archon_share_usd REAL NOT NULL,
                    developer_share_usd REAL NOT NULL,
                    timestamp REAL NOT NULL,
                    billing_period TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_marketplace_listings_partner ON marketplace_listings(partner_id, updated_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_marketplace_revenue_partner_time ON marketplace_revenue_events(partner_id, timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_marketplace_revenue_listing_time ON marketplace_revenue_events(listing_id, timestamp)"
            )

    @staticmethod
    def _to_listing(row: sqlite3.Row | None) -> ListingRecord | None:
        if row is None:
            return None
        return ListingRecord(
            listing_id=str(row["listing_id"]),
            partner_id=str(row["partner_id"]),
            price_tier=str(row["price_tier"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )


class PayoutQueue:
    """Approval-gated payout queue backed by SQLite.

    Example:
        >>> registry = PartnerRegistry(path=":memory:")
        >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
        >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
        >>> queue.list_pending()
        []
    """

    def __init__(
        self,
        registry: PartnerRegistry,
        ledger: RevenueShareLedger,
        *,
        approval_gate: ApprovalGate | None = None,
        stripe_client: StripeConnectClient | None = None,
        path: str | Path = "archon_marketplace_revenue.sqlite3",
        minimum_payout_usd: float = 10.0,
        master_key: bytes | None = None,
    ) -> None:
        self.registry = registry
        self.ledger = ledger
        self.approval_gate = approval_gate or ApprovalGate()
        self.path = Path(path)
        self.minimum_payout_usd = max(0.0, float(minimum_payout_usd))
        self._master_key = master_key or _default_master_key()
        self._owns_stripe_client = False
        self.stripe_client = stripe_client
        self._init_db()

    async def aclose(self) -> None:
        """Close the owned Stripe client when this queue created it.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> __import__("asyncio").run(queue.aclose())
        """

        if self._owns_stripe_client and self.stripe_client is not None:
            await self.stripe_client.aclose()

    def enqueue(
        self,
        partner_id: str,
        period_start: float,
        period_end: float,
        *,
        cycle_id: str | None = None,
    ) -> Pending | None:
        """Queue one developer payout when the threshold is met.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> queue.enqueue("partner-1", 0.0, 1.0) is None
            True
        """

        partner = self._partner(partner_id)
        earnings = self.ledger.aggregate_developer(partner.partner_id, period_start, period_end)
        if earnings.developer_usd < self.minimum_payout_usd:
            return None
        account_id = decrypt_partner_account_id(partner, master_key=self._master_key)
        if not account_id:
            return None

        existing = self._existing_payout(partner.partner_id, period_start, period_end)
        if existing is not None:
            if cycle_id and not existing.cycle_id:
                self._set_cycle(existing.payout_id, cycle_id)
                existing = self.get(existing.payout_id)
            return existing

        created_at = _now()
        payout = Pending(
            payout_id=_payout_id(),
            partner_id=partner.partner_id,
            account_id=account_id,
            amount_usd=_round_usd(earnings.developer_usd),
            period_start=float(period_start),
            period_end=float(period_end),
            status="pending",
            created_at=created_at,
            cycle_id=str(cycle_id or "").strip() or None,
            updated_at=created_at,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO marketplace_payouts(
                    payout_id,
                    partner_id,
                    encrypted_account_json,
                    amount_usd,
                    period_start,
                    period_end,
                    status,
                    created_at,
                    updated_at,
                    approved_at,
                    executed_at,
                    transfer_id,
                    error_text,
                    cycle_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?)
                """,
                (
                    payout.payout_id,
                    payout.partner_id,
                    _encrypt_account(payout.partner_id, payout.account_id, self._master_key),
                    payout.amount_usd,
                    payout.period_start,
                    payout.period_end,
                    payout.status,
                    payout.created_at,
                    payout.updated_at,
                    payout.cycle_id,
                ),
            )
        return payout

    async def approve(
        self,
        payout_id: str,
        *,
        event_sink: EventSink | None = None,
    ) -> Pending:
        """Approve one queued payout through the approval gate.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> queue.get("missing") is None
            True
        """

        payout = self._required_payout(payout_id)
        await self.approval_gate.check(
            action="financial_transaction",
            context={
                "partner_id": payout.partner_id,
                "amount_usd": payout.amount_usd,
                "account_id": payout.account_id,
                "event_sink": event_sink,
            },
            action_id=f"marketplace-payout-{payout.payout_id}",
        )
        self._mark_approved_unchecked(payout.payout_id)
        approved = self.get(payout.payout_id)
        if approved is None:
            raise RuntimeError("Approved payout disappeared.")
        return approved

    async def execute(self, payout_id: str) -> PayoutResult:
        """Execute one approved payout transfer through Stripe Connect.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> queue.get("missing") is None
            True
        """

        payout = self._required_payout(payout_id)
        if payout.status not in {"approved", "failed"}:
            raise ValueError(
                f"Payout '{payout.payout_id}' must be approved or failed before execution."
            )
        try:
            payload = await self._stripe_client().create_transfer(
                payout.account_id,
                payout.amount_usd,
                metadata={
                    "payout_id": payout.payout_id,
                    "partner_id": payout.partner_id,
                    "period_start": payout.period_start,
                    "period_end": payout.period_end,
                },
            )
        except Exception as exc:
            executed_at = _now()
            self._update_payout(
                payout.payout_id,
                status="failed",
                transfer_id=None,
                error_text=str(exc),
                executed_at=executed_at,
            )
            return PayoutResult(
                payout_id=payout.payout_id,
                transfer_id="",
                status="failed",
                executed_at=executed_at,
            )

        executed_at = _now()
        transfer_id = str(payload.get("id") or "")
        self._update_payout(
            payout.payout_id,
            status="paid",
            transfer_id=transfer_id,
            error_text=None,
            executed_at=executed_at,
        )
        return PayoutResult(
            payout_id=payout.payout_id,
            transfer_id=transfer_id,
            status="paid",
            executed_at=executed_at,
        )

    def list_pending(self) -> list[Pending]:
        """List all payouts currently waiting for approval.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> queue.list_pending()
            []
        """

        return self.list_payouts(status_filter="pending")

    def list_payouts(
        self,
        *,
        partner_id: str | None = None,
        status_filter: str | None = None,
        cycle_id: str | None = None,
        period_start: float | None = None,
        period_end: float | None = None,
    ) -> list[Pending]:
        """List queued payouts with optional filters.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> queue.list_payouts()
            []
        """

        query = (
            "SELECT payout_id, partner_id, encrypted_account_json, amount_usd, period_start, "
            "period_end, status, created_at, updated_at, transfer_id, error_text, cycle_id "
            "FROM marketplace_payouts WHERE 1=1"
        )
        params: list[Any] = []
        if partner_id:
            query += " AND partner_id = ?"
            params.append(str(partner_id or "").strip())
        if status_filter:
            normalized = str(status_filter or "").strip().lower()
            if normalized not in PAYOUT_STATUSES:
                raise ValueError(f"Invalid payout status '{status_filter}'.")
            query += " AND status = ?"
            params.append(normalized)
        if cycle_id:
            query += " AND cycle_id = ?"
            params.append(str(cycle_id or "").strip())
        if period_start is not None:
            query += " AND period_start >= ?"
            params.append(float(period_start))
        if period_end is not None:
            query += " AND period_end <= ?"
            params.append(float(period_end))
        query += " ORDER BY created_at DESC, payout_id DESC"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._to_pending(row) for row in rows]

    def get(self, payout_id: str) -> Pending | None:
        """Load one payout row by id.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> queue.get("missing") is None
            True
        """

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payout_id, partner_id, encrypted_account_json, amount_usd, period_start,
                       period_end, status, created_at, updated_at, transfer_id, error_text, cycle_id
                FROM marketplace_payouts
                WHERE payout_id = ?
                """,
                (str(payout_id or "").strip(),),
            ).fetchone()
        return self._to_pending(row) if row is not None else None

    async def retry_failed(self, payout_id: str) -> PayoutResult:
        """Retry a previously failed payout transfer.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> queue.get("missing") is None
            True
        """

        payout = self._required_payout(payout_id)
        if payout.status != "failed":
            raise ValueError(f"Payout '{payout.payout_id}' is not failed.")
        return await self.execute(payout.payout_id)

    def prune(self, *, max_age_seconds: int) -> int:
        """Delete completed payout rows older than the given threshold.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> queue.prune(max_age_seconds=3600)
            0
        """

        if int(max_age_seconds) <= 0:
            raise ValueError("max_age_seconds must be > 0.")
        cutoff = _now() - float(max_age_seconds)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM marketplace_payouts
                WHERE status IN ('paid', 'failed')
                  AND updated_at < ?
                """,
                (cutoff,),
            )
        return int(cursor.rowcount)

    def _existing_payout(
        self,
        partner_id: str,
        period_start: float,
        period_end: float,
    ) -> Pending | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payout_id, partner_id, encrypted_account_json, amount_usd, period_start,
                       period_end, status, created_at, updated_at, transfer_id, error_text, cycle_id
                FROM marketplace_payouts
                WHERE partner_id = ?
                  AND period_start = ?
                  AND period_end = ?
                LIMIT 1
                """,
                (str(partner_id), float(period_start), float(period_end)),
            ).fetchone()
        return self._to_pending(row) if row is not None else None

    def _set_cycle(self, payout_id: str, cycle_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE marketplace_payouts
                SET cycle_id = ?, updated_at = ?
                WHERE payout_id = ?
                """,
                (str(cycle_id or "").strip() or None, _now(), str(payout_id or "").strip()),
            )

    def _mark_approved_unchecked(self, payout_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE marketplace_payouts
                SET status = 'approved',
                    approved_at = ?,
                    updated_at = ?,
                    error_text = NULL
                WHERE payout_id = ?
                """,
                (_now(), _now(), str(payout_id or "").strip()),
            )

    def _partner(self, partner_id: str) -> Partner:
        partner = self.registry.get(str(partner_id or "").strip())
        if partner is None:
            raise KeyError(f"Partner '{partner_id}' not found.")
        return partner

    def _required_payout(self, payout_id: str) -> Pending:
        payout = self.get(payout_id)
        if payout is None:
            raise KeyError(f"Payout '{payout_id}' not found.")
        return payout

    def _update_payout(
        self,
        payout_id: str,
        *,
        status: str,
        transfer_id: str | None,
        error_text: str | None,
        executed_at: float | None = None,
    ) -> None:
        if str(status or "").strip().lower() not in PAYOUT_STATUSES:
            raise ValueError(f"Invalid payout status '{status}'.")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE marketplace_payouts
                SET status = ?,
                    updated_at = ?,
                    executed_at = ?,
                    transfer_id = ?,
                    error_text = ?
                WHERE payout_id = ?
                """,
                (
                    str(status or "").strip().lower(),
                    _now(),
                    float(executed_at) if executed_at is not None else None,
                    str(transfer_id or "").strip() or None,
                    str(error_text or "").strip() or None,
                    str(payout_id or "").strip(),
                ),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _stripe_client(self) -> StripeConnectClient:
        if self.stripe_client is None:
            self.stripe_client = StripeConnectClient()
            self._owns_stripe_client = True
        return self.stripe_client

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS marketplace_payouts (
                    payout_id TEXT PRIMARY KEY,
                    partner_id TEXT NOT NULL,
                    encrypted_account_json TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    period_start REAL NOT NULL,
                    period_end REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    approved_at REAL,
                    executed_at REAL,
                    transfer_id TEXT,
                    error_text TEXT,
                    cycle_id TEXT
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_marketplace_payouts_partner_period ON marketplace_payouts(partner_id, period_start, period_end)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_marketplace_payouts_status ON marketplace_payouts(status, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_marketplace_payouts_cycle ON marketplace_payouts(cycle_id, status, updated_at)"
            )

    def _to_pending(self, row: sqlite3.Row) -> Pending:
        return Pending(
            payout_id=str(row["payout_id"]),
            partner_id=str(row["partner_id"]),
            account_id=_decrypt_account(
                str(row["partner_id"]),
                str(row["encrypted_account_json"]),
                self._master_key,
            ),
            amount_usd=_round_usd(float(row["amount_usd"])),
            period_start=float(row["period_start"]),
            period_end=float(row["period_end"]),
            status=str(row["status"]),
            created_at=float(row["created_at"]),
            transfer_id=str(row["transfer_id"]) if row["transfer_id"] else None,
            cycle_id=str(row["cycle_id"]) if row["cycle_id"] else None,
            updated_at=float(row["updated_at"]) if row["updated_at"] is not None else None,
            error_text=str(row["error_text"]) if row["error_text"] else None,
        )
