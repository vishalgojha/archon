"""Revenue attribution and commission calculations for partners."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from archon.partners.registry import PARTNER_TIER_REVENUE_SHARE, PartnerRegistry


def _now() -> float:
    return time.time()


def _attribution_id() -> str:
    return f"attrib-{uuid.uuid4().hex[:12]}"


def _commission_id() -> str:
    return f"comm-{uuid.uuid4().hex[:12]}"


def _revenue_event_id() -> str:
    return f"rev-{uuid.uuid4().hex[:12]}"


def _period_label(start: float, end: float) -> str:
    begin = datetime.fromtimestamp(start, tz=timezone.utc).date().isoformat()
    finish = datetime.fromtimestamp(end, tz=timezone.utc).date().isoformat()
    return f"{begin}..{finish}"


@dataclass(slots=True)
class Attribution:
    attribution_id: str
    partner_id: str
    customer_id: str
    referral_code: str
    created_at: float = field(default_factory=_now)
    status: str = "active"


@dataclass(slots=True)
class Commission:
    commission_id: str
    partner_id: str
    amount_usd: float
    period: str
    status: str
    transactions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PartnerDashboard:
    attributed_customers: int
    total_revenue: float
    pending_commission: float
    paid_commission: float
    conversion_rate: float


class RevenueShare:
    """SQLite-backed partner attribution and commission service."""

    def __init__(
        self,
        registry: PartnerRegistry,
        path: str | Path = "archon_partner_revenue.sqlite3",
    ) -> None:
        self.registry = registry
        self.path = Path(path)
        self._init_db()

    def attribute_customer(self, customer_id: str, referral_code: str) -> Attribution:
        clean_customer = str(customer_id or "").strip()
        clean_code = str(referral_code or "").strip().upper()
        if not clean_customer:
            raise ValueError("customer_id is required.")
        if not clean_code:
            raise ValueError("referral_code is required.")

        partner = self.registry.get_by_referral_code(clean_code)
        if partner is None:
            raise KeyError(f"Referral code '{clean_code}' not found.")

        row = Attribution(
            attribution_id=_attribution_id(),
            partner_id=partner.partner_id,
            customer_id=clean_customer,
            referral_code=clean_code,
            created_at=_now(),
            status="active",
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO attributions(
                    attribution_id, partner_id, customer_id, referral_code, created_at, status
                ) VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(customer_id) DO UPDATE SET
                    attribution_id=excluded.attribution_id,
                    partner_id=excluded.partner_id,
                    referral_code=excluded.referral_code,
                    created_at=excluded.created_at,
                    status=excluded.status
                """,
                (
                    row.attribution_id,
                    row.partner_id,
                    row.customer_id,
                    row.referral_code,
                    row.created_at,
                    row.status,
                ),
            )

        loaded = self.get_attribution_by_customer(clean_customer)
        if loaded is None:
            raise RuntimeError("Attribution was not persisted.")
        return loaded

    def get_attribution_by_customer(self, customer_id: str) -> Attribution | None:
        with self._connect() as conn:
            record = conn.execute(
                """
                SELECT attribution_id, partner_id, customer_id, referral_code, created_at, status
                FROM attributions
                WHERE customer_id = ?
                """,
                (str(customer_id or "").strip(),),
            ).fetchone()
        return self._to_attribution(record)

    def record_revenue(self, customer_id: str, amount_usd: float, event_type: str) -> str:
        clean_customer = str(customer_id or "").strip()
        if not clean_customer:
            raise ValueError("customer_id is required.")

        event_id = _revenue_event_id()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO revenue_events(event_id, customer_id, amount_usd, event_type, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    clean_customer,
                    float(amount_usd),
                    str(event_type or "").strip() or "unknown",
                    _now(),
                ),
            )
        return event_id

    def calculate_commission(
        self,
        partner_id: str,
        period_start: float,
        period_end: float,
    ) -> Commission:
        clean_partner_id = str(partner_id or "").strip()
        if not clean_partner_id:
            raise ValueError("partner_id is required.")

        partner = self.registry.get(clean_partner_id)
        if partner is None:
            raise KeyError(f"Partner '{clean_partner_id}' not found.")

        start = float(period_start)
        end = float(period_end)
        if end < start:
            raise ValueError("period_end must be >= period_start.")

        with self._connect() as conn:
            records = conn.execute(
                """
                SELECT r.event_id, r.amount_usd
                FROM revenue_events AS r
                INNER JOIN attributions AS a ON a.customer_id = r.customer_id
                WHERE a.partner_id = ?
                  AND r.created_at >= ?
                  AND r.created_at <= ?
                ORDER BY r.created_at ASC, r.event_id ASC
                """,
                (clean_partner_id, start, end),
            ).fetchall()

        gross_revenue = sum(float(row["amount_usd"]) for row in records)
        rev_share = PARTNER_TIER_REVENUE_SHARE.get(partner.tier, 0.0)
        amount = round(gross_revenue * rev_share, 2)
        transactions = [str(row["event_id"]) for row in records]

        row = Commission(
            commission_id=_commission_id(),
            partner_id=clean_partner_id,
            amount_usd=amount,
            period=_period_label(start, end),
            status="pending",
            transactions=transactions,
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO commissions(
                    commission_id,
                    partner_id,
                    amount_usd,
                    period,
                    period_start,
                    period_end,
                    status,
                    transactions,
                    created_at,
                    paid_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    row.commission_id,
                    row.partner_id,
                    row.amount_usd,
                    row.period,
                    start,
                    end,
                    row.status,
                    json.dumps(row.transactions),
                    _now(),
                ),
            )

        return row

    def mark_paid(self, commission_id: str, transaction_ref: str) -> Commission:
        clean_id = str(commission_id or "").strip()
        clean_ref = str(transaction_ref or "").strip()
        if not clean_id:
            raise ValueError("commission_id is required.")
        if not clean_ref:
            raise ValueError("transaction_ref is required.")

        with self._connect() as conn:
            record = conn.execute(
                """
                SELECT commission_id, partner_id, amount_usd, period, status, transactions
                FROM commissions
                WHERE commission_id = ?
                """,
                (clean_id,),
            ).fetchone()
            if record is None:
                raise KeyError(f"Commission '{clean_id}' not found.")

            transactions = json.loads(str(record["transactions"])) if record["transactions"] else []
            if clean_ref not in transactions:
                transactions.append(clean_ref)

            conn.execute(
                """
                UPDATE commissions
                SET status = 'paid', transactions = ?, paid_at = ?
                WHERE commission_id = ?
                """,
                (json.dumps(transactions), _now(), clean_id),
            )

            refreshed = conn.execute(
                """
                SELECT commission_id, partner_id, amount_usd, period, status, transactions
                FROM commissions
                WHERE commission_id = ?
                """,
                (clean_id,),
            ).fetchone()

        if refreshed is None:
            raise RuntimeError("Commission row disappeared during update.")

        return Commission(
            commission_id=str(refreshed["commission_id"]),
            partner_id=str(refreshed["partner_id"]),
            amount_usd=float(refreshed["amount_usd"]),
            period=str(refreshed["period"]),
            status=str(refreshed["status"]),
            transactions=json.loads(str(refreshed["transactions"])) if refreshed["transactions"] else [],
        )

    def get_dashboard(self, partner_id: str) -> PartnerDashboard:
        clean_partner_id = str(partner_id or "").strip()
        if not clean_partner_id:
            raise ValueError("partner_id is required.")

        with self._connect() as conn:
            attributed_customers = conn.execute(
                "SELECT COUNT(*) AS count FROM attributions WHERE partner_id = ?",
                (clean_partner_id,),
            ).fetchone()
            attributed_count = int(attributed_customers["count"]) if attributed_customers else 0

            revenue_row = conn.execute(
                """
                SELECT COALESCE(SUM(r.amount_usd), 0.0) AS total
                FROM revenue_events AS r
                INNER JOIN attributions AS a ON a.customer_id = r.customer_id
                WHERE a.partner_id = ?
                """,
                (clean_partner_id,),
            ).fetchone()
            total_revenue = float(revenue_row["total"] if revenue_row else 0.0)

            pending_row = conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0.0) AS total FROM commissions WHERE partner_id = ? AND status = 'pending'",
                (clean_partner_id,),
            ).fetchone()
            paid_row = conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0.0) AS total FROM commissions WHERE partner_id = ? AND status = 'paid'",
                (clean_partner_id,),
            ).fetchone()

            converted_row = conn.execute(
                """
                SELECT COUNT(DISTINCT r.customer_id) AS count
                FROM revenue_events AS r
                INNER JOIN attributions AS a ON a.customer_id = r.customer_id
                WHERE a.partner_id = ?
                """,
                (clean_partner_id,),
            ).fetchone()
            converted_count = int(converted_row["count"]) if converted_row else 0

        conversion_rate = (converted_count / attributed_count) if attributed_count else 0.0
        return PartnerDashboard(
            attributed_customers=attributed_count,
            total_revenue=round(total_revenue, 2),
            pending_commission=round(float(pending_row["total"] if pending_row else 0.0), 2),
            paid_commission=round(float(paid_row["total"] if paid_row else 0.0), 2),
            conversion_rate=round(conversion_rate, 4),
        )

    def get_revenue_for_customers(self, customer_ids: list[str]) -> float:
        normalized = [str(item or "").strip() for item in customer_ids if str(item or "").strip()]
        if not normalized:
            return 0.0

        placeholders = ",".join("?" for _ in normalized)
        query = f"SELECT COALESCE(SUM(amount_usd), 0.0) AS total FROM revenue_events WHERE customer_id IN ({placeholders})"
        with self._connect() as conn:
            row = conn.execute(query, tuple(normalized)).fetchone()
        return round(float(row["total"] if row else 0.0), 2)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attributions (
                    attribution_id TEXT PRIMARY KEY,
                    partner_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL UNIQUE,
                    referral_code TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS revenue_events (
                    event_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS commissions (
                    commission_id TEXT PRIMARY KEY,
                    partner_id TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    period TEXT NOT NULL,
                    period_start REAL NOT NULL,
                    period_end REAL NOT NULL,
                    status TEXT NOT NULL,
                    transactions TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    paid_at REAL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_attributions_partner ON attributions(partner_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_revenue_customer ON revenue_events(customer_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_revenue_created ON revenue_events(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_commissions_partner ON commissions(partner_id, status)")

    @staticmethod
    def _to_attribution(record: sqlite3.Row | None) -> Attribution | None:
        if record is None:
            return None
        return Attribution(
            attribution_id=str(record["attribution_id"]),
            partner_id=str(record["partner_id"]),
            customer_id=str(record["customer_id"]),
            referral_code=str(record["referral_code"]),
            created_at=float(record["created_at"]),
            status=str(record["status"]),
        )
