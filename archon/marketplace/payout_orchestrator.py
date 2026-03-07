"""Monthly payout orchestration and developer revenue reporting."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from archon.compliance.retention import RetentionRule
from archon.core.approval_gate import ApprovalGate, EventSink
from archon.marketplace.connect import decrypt_partner_account_id
from archon.marketplace.revenue_share import (
    DeveloperEarnings,
    PayoutQueue,
    PayoutResult,
    Pending,
    RevenueShareLedger,
    _now,
    _round_usd,
)
from archon.partners.registry import PartnerRegistry

PAYOUT_CYCLE_RETENTION_RULE = RetentionRule(
    entity_type="marketplace_payout_cycle",
    retention_days=3650,
    action="archive",
)
REVENUE_REPORT_RETENTION_RULE = RetentionRule(
    entity_type="marketplace_revenue_report",
    retention_days=365,
    action="archive",
)


def _cycle_id() -> str:
    return f"cycle-{uuid.uuid4().hex[:12]}"


def _period_text(period_start: float, period_end: float) -> str:
    return f"{int(period_start)}:{int(period_end)}"


@dataclass(slots=True, frozen=True)
class CycleResult:
    """Summary of one payout cycle execution.

    Example:
        >>> CycleResult("cycle-1", 0.0, 1.0, 1, 0, 10.0, 0.0, [], 1.0).partners_paid
        1
    """

    cycle_id: str
    period_start: float
    period_end: float
    partners_paid: int
    partners_skipped: int
    total_paid_usd: float
    total_skipped_usd: float
    failures: list[str]
    executed_at: float


@dataclass(slots=True, frozen=True)
class RevenueReport:
    """Developer-facing revenue report payload.

    Example:
        >>> earnings = DeveloperEarnings("partner-1", 10.0, 7.0, 3.0, 1, 0.0, 1.0)
        >>> RevenueReport("partner-1", "2026-03", earnings, [], [], 0.0).partner_id
        'partner-1'
    """

    partner_id: str
    period: str
    earnings: DeveloperEarnings
    payouts: list[Pending]
    listing_breakdown: list[dict[str, Any]]
    trend_vs_prior_period: float


class PayoutOrchestrator:
    """Run approval-gated monthly payout cycles for active developers.

    Example:
        >>> registry = PartnerRegistry(path=":memory:")
        >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
        >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
        >>> orchestrator = PayoutOrchestrator(registry=registry, ledger=ledger, payout_queue=queue, path=":memory:")
        >>> orchestrator.get_cycle("missing") is None
        True
    """

    def __init__(
        self,
        registry: PartnerRegistry,
        ledger: RevenueShareLedger,
        payout_queue: PayoutQueue,
        *,
        approval_gate: ApprovalGate | None = None,
        path: str | Path = "archon_marketplace_cycles.sqlite3",
    ) -> None:
        self.registry = registry
        self.ledger = ledger
        self.payout_queue = payout_queue
        self.approval_gate = approval_gate or payout_queue.approval_gate
        self.path = Path(path)
        self._scheduler: Any | None = None
        self._init_db()

    async def run_cycle(
        self,
        period_start: float,
        period_end: float,
        *,
        event_sink: EventSink | None = None,
    ) -> CycleResult:
        """Run one payout cycle with a single batch approval decision.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> orchestrator = PayoutOrchestrator(registry=registry, ledger=ledger, payout_queue=queue, path=":memory:")
            >>> result = __import__("asyncio").run(orchestrator.run_cycle(0.0, 1.0))
            >>> result.partners_paid
            0
        """

        start = float(period_start)
        end = float(period_end)
        if end < start:
            raise ValueError("period_end must be >= period_start.")

        cycle_id = _cycle_id()
        eligible: list[Pending] = []
        skipped_count = 0
        skipped_usd = 0.0
        self._save_cycle_placeholder(cycle_id, start, end)

        for partner in self.registry.list(status_filter="active"):
            if not decrypt_partner_account_id(
                partner,
                master_key=getattr(self.payout_queue, "_master_key", None),
            ):
                skipped_count += 1
                continue
            earnings = self.ledger.aggregate_developer(partner.partner_id, start, end)
            if earnings.developer_usd < self.payout_queue.minimum_payout_usd:
                skipped_count += 1
                skipped_usd += earnings.developer_usd
                continue
            payout = self.payout_queue.enqueue(
                partner.partner_id,
                start,
                end,
                cycle_id=cycle_id,
            )
            if payout is None:
                skipped_count += 1
                skipped_usd += earnings.developer_usd
                continue
            eligible.append(payout)

        total_paid_usd = _round_usd(sum(row.amount_usd for row in eligible))
        if eligible:
            await self.approval_gate.check(
                action="financial_transaction",
                context={
                    "partner_count": len(eligible),
                    "total_payout_usd": total_paid_usd,
                    "period": _period_text(start, end),
                    "event_sink": event_sink,
                },
                action_id=f"marketplace-cycle-{cycle_id}",
            )
            for payout in eligible:
                self.payout_queue._mark_approved_unchecked(payout.payout_id)
            results = await asyncio.gather(
                *(self.payout_queue.execute(payout.payout_id) for payout in eligible)
            )
        else:
            results = []

        failures = [row.payout_id for row in results if row.status != "paid"]
        paid_payouts = [
            row
            for row in (
                self.payout_queue.get(result_row.payout_id)
                for result_row in results
                if result_row.status == "paid"
            )
            if row is not None
        ]
        result = CycleResult(
            cycle_id=cycle_id,
            period_start=start,
            period_end=end,
            partners_paid=sum(1 for row in results if row.status == "paid"),
            partners_skipped=skipped_count,
            total_paid_usd=_round_usd(sum(row.amount_usd for row in paid_payouts)),
            total_skipped_usd=_round_usd(skipped_usd),
            failures=failures,
            executed_at=_now(),
        )
        self._save_cycle_result(result)
        return result

    async def retry_failures(self, cycle_id: str) -> list[PayoutResult]:
        """Retry only failed payouts from an existing cycle.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> orchestrator = PayoutOrchestrator(registry=registry, ledger=ledger, payout_queue=queue, path=":memory:")
            >>> __import__("asyncio").run(orchestrator.retry_failures("missing"))
            []
        """

        failed = self.payout_queue.list_payouts(
            cycle_id=str(cycle_id or "").strip(), status_filter="failed"
        )
        if not failed:
            return []
        results = await asyncio.gather(
            *(self.payout_queue.retry_failed(row.payout_id) for row in failed)
        )
        current = self.get_cycle(cycle_id)
        if current is not None:
            refreshed_failures = [
                row.payout_id
                for row in self.payout_queue.list_payouts(cycle_id=cycle_id, status_filter="failed")
            ]
            self._save_cycle_result(
                CycleResult(
                    cycle_id=current.cycle_id,
                    period_start=current.period_start,
                    period_end=current.period_end,
                    partners_paid=len(
                        self.payout_queue.list_payouts(cycle_id=cycle_id, status_filter="paid")
                    ),
                    partners_skipped=current.partners_skipped,
                    total_paid_usd=_round_usd(
                        sum(
                            row.amount_usd
                            for row in self.payout_queue.list_payouts(
                                cycle_id=cycle_id, status_filter="paid"
                            )
                        )
                    ),
                    total_skipped_usd=current.total_skipped_usd,
                    failures=refreshed_failures,
                    executed_at=_now(),
                )
            )
        return list(results)

    def get_cycle(self, cycle_id: str) -> CycleResult | None:
        """Load one stored payout cycle summary by id.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> orchestrator = PayoutOrchestrator(registry=registry, ledger=ledger, payout_queue=queue, path=":memory:")
            >>> orchestrator.get_cycle("missing") is None
            True
        """

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT cycle_id, period_start, period_end, partners_paid, partners_skipped,
                       total_paid_usd, total_skipped_usd, failures_json, executed_at
                FROM marketplace_payout_cycles
                WHERE cycle_id = ?
                """,
                (str(cycle_id or "").strip(),),
            ).fetchone()
        if row is None:
            return None
        return CycleResult(
            cycle_id=str(row["cycle_id"]),
            period_start=float(row["period_start"]),
            period_end=float(row["period_end"]),
            partners_paid=int(row["partners_paid"]),
            partners_skipped=int(row["partners_skipped"]),
            total_paid_usd=_round_usd(float(row["total_paid_usd"])),
            total_skipped_usd=_round_usd(float(row["total_skipped_usd"])),
            failures=json.loads(str(row["failures_json"])) if row["failures_json"] else [],
            executed_at=float(row["executed_at"]),
        )

    def schedule(self) -> str:
        """Start monthly scheduling when APScheduler is available, otherwise fall back to manual.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> orchestrator = PayoutOrchestrator(registry=registry, ledger=ledger, payout_queue=queue, path=":memory:")
            >>> orchestrator.schedule() in {"manual", "apscheduler"}
            True
        """

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except Exception:
            return "manual"
        if self._scheduler is None:
            scheduler = BackgroundScheduler(timezone="UTC")
            scheduler.add_job(
                self._run_previous_month_safely,
                "cron",
                day=1,
                hour=0,
                minute=5,
                id="archon-marketplace-monthly-payouts",
                replace_existing=True,
            )
            scheduler.start()
            self._scheduler = scheduler
        return "apscheduler"

    def prune(self, *, max_age_seconds: int) -> int:
        """Delete stored cycle summaries older than the age threshold.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> orchestrator = PayoutOrchestrator(registry=registry, ledger=ledger, payout_queue=queue, path=":memory:")
            >>> orchestrator.prune(max_age_seconds=3600)
            0
        """

        if int(max_age_seconds) <= 0:
            raise ValueError("max_age_seconds must be > 0.")
        cutoff = _now() - float(max_age_seconds)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM marketplace_payout_cycles WHERE executed_at < ?",
                (cutoff,),
            )
        return int(cursor.rowcount)

    def _run_previous_month_safely(self) -> None:
        now = time.gmtime()
        end = time.mktime((now.tm_year, now.tm_mon, 1, 0, 0, 0, 0, 0, -1))
        start_tuple = time.gmtime(end - 1)
        start = time.mktime((start_tuple.tm_year, start_tuple.tm_mon, 1, 0, 0, 0, 0, 0, -1))
        try:
            asyncio.run(self.run_cycle(start, end))
        except Exception:
            return

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS marketplace_payout_cycles (
                    cycle_id TEXT PRIMARY KEY,
                    period_start REAL NOT NULL,
                    period_end REAL NOT NULL,
                    partners_paid INTEGER NOT NULL,
                    partners_skipped INTEGER NOT NULL,
                    total_paid_usd REAL NOT NULL,
                    total_skipped_usd REAL NOT NULL,
                    failures_json TEXT NOT NULL,
                    executed_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_marketplace_payout_cycles_executed ON marketplace_payout_cycles(executed_at)"
            )

    def _save_cycle_placeholder(
        self, cycle_id: str, period_start: float, period_end: float
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO marketplace_payout_cycles(
                    cycle_id,
                    period_start,
                    period_end,
                    partners_paid,
                    partners_skipped,
                    total_paid_usd,
                    total_skipped_usd,
                    failures_json,
                    executed_at
                ) VALUES (?, ?, ?, 0, 0, 0.0, 0.0, '[]', ?)
                """,
                (cycle_id, float(period_start), float(period_end), _now()),
            )

    def _save_cycle_result(self, result: CycleResult) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO marketplace_payout_cycles(
                    cycle_id,
                    period_start,
                    period_end,
                    partners_paid,
                    partners_skipped,
                    total_paid_usd,
                    total_skipped_usd,
                    failures_json,
                    executed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.cycle_id,
                    result.period_start,
                    result.period_end,
                    int(result.partners_paid),
                    int(result.partners_skipped),
                    result.total_paid_usd,
                    result.total_skipped_usd,
                    json.dumps(list(result.failures), separators=(",", ":")),
                    result.executed_at,
                ),
            )


class PartnerRevenueReport:
    """Generate partner revenue summaries plus exports.

    Example:
        >>> registry = PartnerRegistry(path=":memory:")
        >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
        >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
        >>> reporter = PartnerRevenueReport(ledger=ledger, payout_queue=queue)
        >>> reporter.generate("partner-1", 0.0, 1.0).partner_id
        'partner-1'
    """

    def __init__(self, *, ledger: RevenueShareLedger, payout_queue: PayoutQueue) -> None:
        self.ledger = ledger
        self.payout_queue = payout_queue

    def generate(self, partner_id: str, period_start: float, period_end: float) -> RevenueReport:
        """Generate one developer revenue report for the given period.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> report = PartnerRevenueReport(ledger=ledger, payout_queue=queue).generate("partner-1", 0.0, 1.0)
            >>> report.period
            '0:1'
        """

        clean_partner_id = str(partner_id or "").strip()
        if not clean_partner_id:
            raise ValueError("partner_id is required.")
        start = float(period_start)
        end = float(period_end)
        earnings = self.ledger.aggregate_developer(clean_partner_id, start, end)
        payouts = self.payout_queue.list_payouts(
            partner_id=clean_partner_id,
            period_start=start,
            period_end=end,
        )
        listing_breakdown = self.ledger.listing_breakdown(clean_partner_id, start, end)
        previous_duration = max(0.0, end - start)
        prior_start = max(0.0, start - previous_duration)
        prior_end = start
        prior = self.ledger.aggregate_developer(clean_partner_id, prior_start, prior_end)
        trend = self._trend(current=earnings.developer_usd, prior=prior.developer_usd)
        return RevenueReport(
            partner_id=clean_partner_id,
            period=_period_text(start, end),
            earnings=earnings,
            payouts=payouts,
            listing_breakdown=listing_breakdown,
            trend_vs_prior_period=trend,
        )

    def export_pdf(self, report: RevenueReport, path: str | Path) -> Path:
        """Export one report to PDF when available, otherwise write a text fallback.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> report = PartnerRevenueReport(ledger=ledger, payout_queue=queue).generate("partner-1", 0.0, 1.0)
            >>> output = PartnerRevenueReport(ledger=ledger, payout_queue=queue).export_pdf(report, Path("archon/tests/_tmp_reports/report.pdf"))
            >>> output.suffix in {".pdf", ".txt"}
            True
        """

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            from reportlab.pdfgen import canvas
        except Exception:
            fallback = target.with_suffix(".txt")
            fallback.write_text(self._report_text(report), encoding="utf-8")
            return fallback

        page = canvas.Canvas(str(target))
        y = 800
        for line in self._report_text(report).splitlines():
            page.drawString(36, y, line[:100])
            y -= 16
            if y < 48:
                page.showPage()
                y = 800
        page.save()
        return target

    def export_json(self, report: RevenueReport, path: str | Path) -> Path:
        """Export one report to JSON.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> ledger = RevenueShareLedger(registry=registry, path=":memory:")
            >>> queue = PayoutQueue(registry=registry, ledger=ledger, path=":memory:")
            >>> report = PartnerRevenueReport(ledger=ledger, payout_queue=queue).generate("partner-1", 0.0, 1.0)
            >>> PartnerRevenueReport(ledger=ledger, payout_queue=queue).export_json(report, Path("archon/tests/_tmp_reports/report.json")).suffix
            '.json'
        """

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "partner_id": report.partner_id,
            "period": report.period,
            "earnings": asdict(report.earnings),
            "payouts": [asdict(item) for item in report.payouts],
            "listing_breakdown": report.listing_breakdown,
            "trend_vs_prior_period": report.trend_vs_prior_period,
        }
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return target

    @staticmethod
    def _trend(*, current: float, prior: float) -> float:
        if prior <= 0:
            return 100.0 if current > 0 else 0.0
        return round(((current - prior) / prior) * 100.0, 2)

    @staticmethod
    def _report_text(report: RevenueReport) -> str:
        lines = [
            f"Partner: {report.partner_id}",
            f"Period: {report.period}",
            f"Developer Earnings: ${report.earnings.developer_usd:.2f}",
            f"Gross Revenue: ${report.earnings.gross_usd:.2f}",
            f"ARCHON Share: ${report.earnings.archon_usd:.2f}",
            f"Trend vs prior period: {report.trend_vs_prior_period:.2f}%",
            "Listings:",
        ]
        for row in report.listing_breakdown:
            lines.append(
                f"- {row['listing_id']}: gross=${row['gross_usd']:.2f} dev=${row['developer_usd']:.2f}"
            )
        lines.append("Payouts:")
        for payout in report.payouts:
            lines.append(f"- {payout.payout_id}: ${payout.amount_usd:.2f} {payout.status}")
        return "\n".join(lines)
