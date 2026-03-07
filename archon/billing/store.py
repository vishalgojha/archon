"""SQLite persistence for ARCHON billing state."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from archon.billing.models import (
    BillingCustomer,
    BillingInvoice,
    BillingSubscription,
    InvoiceLine,
    SubscriptionChange,
    UsageRecord,
    WebhookEvent,
)


class BillingStore:
    """Persist billing entities in SQLite."""

    def __init__(self, path: str | Path = "archon_billing.sqlite3") -> None:
        self.path = Path(path)
        self._init_db()

    def upsert_customer(self, customer: BillingCustomer) -> BillingCustomer:
        """Create or update one customer row.

        Example:
            >>> store = BillingStore(":memory:")
            >>> store.upsert_customer(BillingCustomer(tenant_id="tenant-a")).tenant_id
            'tenant-a'
        """

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO customers(tenant_id, customer_id, email, name, status, external_customer_id, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    customer_id=excluded.customer_id,
                    email=excluded.email,
                    name=excluded.name,
                    status=excluded.status,
                    external_customer_id=excluded.external_customer_id,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    customer.tenant_id,
                    customer.customer_id,
                    customer.email,
                    customer.name,
                    customer.status,
                    customer.external_customer_id,
                    json.dumps(customer.metadata, separators=(",", ":")),
                    customer.created_at,
                    customer.updated_at,
                ),
            )
        loaded = self.get_customer(customer.tenant_id)
        if loaded is None:
            raise RuntimeError("Customer row not found after upsert.")
        return loaded

    def get_customer(self, tenant_id: str) -> BillingCustomer | None:
        """Load one customer row by tenant id."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM customers WHERE tenant_id = ?",
                (str(tenant_id),),
            ).fetchone()
        return _customer_from_row(row)

    def upsert_subscription(self, subscription: BillingSubscription) -> BillingSubscription:
        """Create or update the active subscription for one tenant."""

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO subscriptions(tenant_id, subscription_id, plan_id, status, external_subscription_id, period_start, period_end, cancel_at_period_end, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    subscription_id=excluded.subscription_id,
                    plan_id=excluded.plan_id,
                    status=excluded.status,
                    external_subscription_id=excluded.external_subscription_id,
                    period_start=excluded.period_start,
                    period_end=excluded.period_end,
                    cancel_at_period_end=excluded.cancel_at_period_end,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    subscription.tenant_id,
                    subscription.subscription_id,
                    subscription.plan_id,
                    subscription.status,
                    subscription.external_subscription_id,
                    subscription.period_start,
                    subscription.period_end,
                    1 if subscription.cancel_at_period_end else 0,
                    json.dumps(subscription.metadata, separators=(",", ":")),
                    subscription.created_at,
                    subscription.updated_at,
                ),
            )
        loaded = self.get_subscription(subscription.tenant_id)
        if loaded is None:
            raise RuntimeError("Subscription row not found after upsert.")
        return loaded

    def get_subscription(self, tenant_id: str) -> BillingSubscription | None:
        """Load the active subscription for one tenant."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE tenant_id = ?",
                (str(tenant_id),),
            ).fetchone()
        return _subscription_from_row(row)

    def record_subscription_change(self, change: SubscriptionChange) -> SubscriptionChange:
        """Append one plan-change event."""

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO subscription_changes(change_id, tenant_id, plan_id, effective_at, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    change.change_id,
                    change.tenant_id,
                    change.plan_id,
                    change.effective_at,
                    change.created_at,
                ),
            )
        return change

    def list_subscription_changes(
        self,
        tenant_id: str,
        *,
        end: float | None = None,
    ) -> list[SubscriptionChange]:
        """List plan changes for one tenant ordered by effective time."""

        query = "SELECT * FROM subscription_changes WHERE tenant_id = ?"
        params: list[float | str] = [str(tenant_id)]
        if end is not None:
            query += " AND effective_at < ?"
            params.append(float(end))
        query += " ORDER BY effective_at ASC, created_at ASC, change_id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [_change_from_row(row) for row in rows]

    def record_usage(self, usage: UsageRecord) -> UsageRecord:
        """Append one metered usage record."""

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_events(usage_id, tenant_id, meter_type, quantity, amount_usd, provider, model, action_type, task_id, timestamp, metadata_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usage.usage_id,
                    usage.tenant_id,
                    usage.meter_type,
                    usage.quantity,
                    usage.amount_usd,
                    usage.provider,
                    usage.model,
                    usage.action_type,
                    usage.task_id,
                    usage.timestamp,
                    json.dumps(usage.metadata, separators=(",", ":")),
                ),
            )
        return usage

    def list_usage(self, tenant_id: str, *, start: float, end: float) -> list[UsageRecord]:
        """List usage rows for one tenant between timestamps."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM usage_events
                WHERE tenant_id = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC, usage_id ASC
                """,
                (str(tenant_id), float(start), float(end)),
            ).fetchall()
        return [_usage_from_row(row) for row in rows]

    def save_invoice(self, invoice: BillingInvoice) -> BillingInvoice:
        """Persist one invoice document and its lines."""

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO invoices(invoice_id, tenant_id, subscription_id, plan_id, period_start, period_end, subtotal_usd, tax_usd, total_usd, currency, status, external_invoice_id, metadata_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice.invoice_id,
                    invoice.tenant_id,
                    invoice.subscription_id,
                    invoice.plan_id,
                    invoice.period_start,
                    invoice.period_end,
                    invoice.subtotal_usd,
                    invoice.tax_usd,
                    invoice.total_usd,
                    invoice.currency,
                    invoice.status,
                    invoice.external_invoice_id,
                    json.dumps(invoice.metadata, separators=(",", ":")),
                    invoice.created_at,
                    invoice.updated_at,
                ),
            )
            conn.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", (invoice.invoice_id,))
            for index, line in enumerate(invoice.lines):
                conn.execute(
                    """
                    INSERT INTO invoice_lines(invoice_id, line_index, description, meter_type, quantity, unit_amount_usd, amount_usd, metadata_json)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice.invoice_id,
                        index,
                        line.description,
                        line.meter_type,
                        line.quantity,
                        line.unit_amount_usd,
                        line.amount_usd,
                        json.dumps(line.metadata, separators=(",", ":")),
                    ),
                )
        loaded = self.get_invoice(invoice.tenant_id, invoice.invoice_id)
        if loaded is None:
            raise RuntimeError("Invoice row not found after save.")
        return loaded

    def get_invoice(self, tenant_id: str, invoice_id: str) -> BillingInvoice | None:
        """Load one invoice by tenant and local invoice id."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM invoices WHERE tenant_id = ? AND invoice_id = ?",
                (str(tenant_id), str(invoice_id)),
            ).fetchone()
            if row is None:
                return None
            lines = self._invoice_lines(conn, str(row["invoice_id"]))
        return _invoice_from_row(row, lines)

    def list_invoices(self, tenant_id: str, *, limit: int = 10) -> list[BillingInvoice]:
        """List recent invoices for one tenant."""

        bounded = max(1, min(int(limit), 100))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM invoices WHERE tenant_id = ? ORDER BY period_end DESC, invoice_id DESC LIMIT ?",
                (str(tenant_id), bounded),
            ).fetchall()
            return [
                _invoice_from_row(row, self._invoice_lines(conn, str(row["invoice_id"])))
                for row in rows
            ]

    def find_invoice_by_external_id(self, external_invoice_id: str) -> BillingInvoice | None:
        """Load one invoice by Stripe invoice id."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM invoices WHERE external_invoice_id = ?",
                (str(external_invoice_id),),
            ).fetchone()
            if row is None:
                return None
            lines = self._invoice_lines(conn, str(row["invoice_id"]))
        return _invoice_from_row(row, lines)

    def mark_invoice_paid(self, invoice_id: str, *, paid_at: float) -> BillingInvoice:
        """Mark one invoice as paid and return the refreshed document."""

        with self._connect() as conn:
            conn.execute(
                "UPDATE invoices SET status = 'paid', updated_at = ? WHERE invoice_id = ?",
                (float(paid_at), str(invoice_id)),
            )
        row = self.find_invoice_by_id(invoice_id)
        if row is None:
            raise KeyError(f"Invoice '{invoice_id}' not found.")
        return row

    def update_invoice_status(
        self,
        invoice_id: str,
        *,
        status: str,
        updated_at: float | None = None,
    ) -> BillingInvoice:
        """Update one invoice status and return the refreshed document.

        Example:
            >>> store = BillingStore(":memory:")
            >>> hasattr(store, "update_invoice_status")
            True
        """

        with self._connect() as conn:
            conn.execute(
                "UPDATE invoices SET status = ?, updated_at = ? WHERE invoice_id = ?",
                (str(status), float(time.time() if updated_at is None else updated_at), str(invoice_id)),
            )
        row = self.find_invoice_by_id(invoice_id)
        if row is None:
            raise KeyError(f"Invoice '{invoice_id}' not found.")
        return row

    def find_invoice_by_id(self, invoice_id: str) -> BillingInvoice | None:
        """Load one invoice by local invoice id."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM invoices WHERE invoice_id = ?",
                (str(invoice_id),),
            ).fetchone()
            if row is None:
                return None
            lines = self._invoice_lines(conn, str(row["invoice_id"]))
        return _invoice_from_row(row, lines)

    def record_webhook(self, event: WebhookEvent, *, status: str) -> WebhookEvent:
        """Persist a processed webhook event."""

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO webhooks(event_id, event_type, created_at, status, payload_json)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.created_at,
                    status,
                    json.dumps(event.payload, separators=(",", ":")),
                ),
            )
        return event

    def has_processed_webhook(self, event_id: str) -> bool:
        """Return whether a webhook event id has already been stored."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM webhooks WHERE event_id = ?",
                (str(event_id),),
            ).fetchone()
        return row is not None

    def _invoice_lines(self, conn: sqlite3.Connection, invoice_id: str) -> list[InvoiceLine]:
        rows = conn.execute(
            "SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY line_index ASC",
            (invoice_id,),
        ).fetchall()
        return [_line_from_row(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    tenant_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    external_customer_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    tenant_id TEXT PRIMARY KEY,
                    subscription_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    external_subscription_id TEXT,
                    period_start REAL NOT NULL,
                    period_end REAL NOT NULL,
                    cancel_at_period_end INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscription_changes (
                    change_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    effective_at REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usage_events (
                    usage_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    meter_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    amount_usd REAL NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS invoices (
                    invoice_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    subscription_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    period_start REAL NOT NULL,
                    period_end REAL NOT NULL,
                    subtotal_usd REAL NOT NULL,
                    tax_usd REAL NOT NULL,
                    total_usd REAL NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    external_invoice_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS invoice_lines (
                    invoice_id TEXT NOT NULL,
                    line_index INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    meter_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    unit_amount_usd REAL NOT NULL,
                    amount_usd REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY(invoice_id, line_index),
                    FOREIGN KEY(invoice_id) REFERENCES invoices(invoice_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS webhooks (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_usage_tenant_time ON usage_events(tenant_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_changes_tenant_time ON subscription_changes(tenant_id, effective_at);
                CREATE INDEX IF NOT EXISTS idx_invoices_tenant_period ON invoices(tenant_id, period_end);
                """
            )


def _safe_json_dict(raw: str) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _customer_from_row(row: sqlite3.Row | None) -> BillingCustomer | None:
    if row is None:
        return None
    return BillingCustomer(
        tenant_id=str(row["tenant_id"]),
        customer_id=str(row["customer_id"]),
        email=str(row["email"]),
        name=str(row["name"]),
        status=str(row["status"]),
        external_customer_id=str(row["external_customer_id"]) or None,
        metadata=_safe_json_dict(str(row["metadata_json"])),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


def _subscription_from_row(row: sqlite3.Row | None) -> BillingSubscription | None:
    if row is None:
        return None
    return BillingSubscription(
        tenant_id=str(row["tenant_id"]),
        plan_id=str(row["plan_id"]),
        subscription_id=str(row["subscription_id"]),
        status=str(row["status"]),
        external_subscription_id=str(row["external_subscription_id"]) or None,
        period_start=float(row["period_start"]),
        period_end=float(row["period_end"]),
        cancel_at_period_end=bool(int(row["cancel_at_period_end"])),
        metadata=_safe_json_dict(str(row["metadata_json"])),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


def _change_from_row(row: sqlite3.Row) -> SubscriptionChange:
    return SubscriptionChange(
        tenant_id=str(row["tenant_id"]),
        plan_id=str(row["plan_id"]),
        effective_at=float(row["effective_at"]),
        change_id=str(row["change_id"]),
        created_at=float(row["created_at"]),
    )


def _usage_from_row(row: sqlite3.Row) -> UsageRecord:
    return UsageRecord(
        tenant_id=str(row["tenant_id"]),
        meter_type=str(row["meter_type"]),
        quantity=float(row["quantity"]),
        amount_usd=float(row["amount_usd"]),
        usage_id=str(row["usage_id"]),
        provider=str(row["provider"]),
        model=str(row["model"]),
        action_type=str(row["action_type"]),
        task_id=str(row["task_id"]),
        timestamp=float(row["timestamp"]),
        metadata=_safe_json_dict(str(row["metadata_json"])),
    )


def _line_from_row(row: sqlite3.Row) -> InvoiceLine:
    return InvoiceLine(
        description=str(row["description"]),
        meter_type=str(row["meter_type"]),
        quantity=float(row["quantity"]),
        unit_amount_usd=float(row["unit_amount_usd"]),
        amount_usd=float(row["amount_usd"]),
        metadata=_safe_json_dict(str(row["metadata_json"])),
    )


def _invoice_from_row(row: sqlite3.Row, lines: list[InvoiceLine]) -> BillingInvoice:
    return BillingInvoice(
        tenant_id=str(row["tenant_id"]),
        plan_id=str(row["plan_id"]),
        subscription_id=str(row["subscription_id"]),
        period_start=float(row["period_start"]),
        period_end=float(row["period_end"]),
        lines=lines,
        invoice_id=str(row["invoice_id"]),
        subtotal_usd=float(row["subtotal_usd"]),
        tax_usd=float(row["tax_usd"]),
        total_usd=float(row["total_usd"]),
        currency=str(row["currency"]),
        status=str(row["status"]),
        external_invoice_id=str(row["external_invoice_id"]) or None,
        metadata=_safe_json_dict(str(row["metadata_json"])),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )
