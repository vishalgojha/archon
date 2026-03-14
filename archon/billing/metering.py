"""Append-only tenant usage metering for Stripe metered billing."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from archon.billing.stripe_client import StripeClient, UsageRecord
from archon.compliance.encryption import EncryptionLayer
from archon.compliance.retention import RetentionRule
from archon.core.approval_gate import ApprovalGate, EventSink

SUPPORTED_METRICS: tuple[str, ...] = (
    "tokens_input",
    "tokens_output",
    "agent_runs",
    "emails_sent",
    "whatsapp_sent",
    "vision_actions",
    "memory_reads",
    "memory_writes",
    "federation_tasks",
)

METER_EVENT_RETENTION_RULE = RetentionRule(
    entity_type="meter_event",
    retention_days=365,
    action="archive",
)


def _now() -> float:
    return time.time()


def _event_id() -> str:
    return f"meter_{uuid.uuid4().hex[:12]}"


def _default_master_key() -> bytes:
    env = str(os.getenv("ARCHON_MASTER_KEY", "")).strip()
    if env:
        try:
            return EncryptionLayer.master_key_from_env()
        except ValueError:
            pass
    return b"a" * 32


@dataclass(slots=True, frozen=True)
class MeterEvent:
    """One append-only usage meter event.

    Example:
        >>> MeterEvent("evt", "tenant-a", "agent_runs", 1.0, 1.0, {}).metric
        'agent_runs'
    """

    event_id: str
    tenant_id: str
    metric: str
    quantity: float
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)


class UsageMeter:
    """Track tenant usage and flush metered aggregates to Stripe.

    Example:
        >>> meter = UsageMeter(path=":memory:")
        >>> meter.aggregate("tenant-a", "agent_runs", 0.0, 10.0)
        0.0
    """

    def __init__(
        self,
        path: str | Path = "archon_metering.sqlite3",
        *,
        stripe_client: StripeClient | None = None,
        approval_gate: ApprovalGate | None = None,
        metric_item_ids: dict[str, str] | None = None,
        master_key: bytes | None = None,
    ) -> None:
        self.path = Path(path)
        self.stripe_client = stripe_client or StripeClient()
        self.approval_gate = approval_gate or ApprovalGate()
        self.metric_item_ids = {metric: f"si_{metric}" for metric in SUPPORTED_METRICS}
        if metric_item_ids:
            self.metric_item_ids.update(
                {str(key): str(value) for key, value in metric_item_ids.items() if value}
            )
        self._master_key = master_key or _default_master_key()
        self._aggregate_history: dict[tuple[str, str, float, float], float] = {}
        self._init_db()

    def record(
        self,
        tenant_id: str,
        metric: str,
        quantity: float,
        metadata: dict[str, Any] | None = None,
    ) -> MeterEvent:
        """Append one tenant usage event.

        Example:
            >>> meter = UsageMeter(path=":memory:")
            >>> meter.record("tenant-a", "agent_runs", 1.0, {}).tenant_id
            'tenant-a'
        """

        normalized_metric = str(metric or "").strip()
        if normalized_metric not in SUPPORTED_METRICS:
            raise ValueError(f"Unsupported metric '{metric}'.")
        event = MeterEvent(
            event_id=_event_id(),
            tenant_id=str(tenant_id or "").strip(),
            metric=normalized_metric,
            quantity=float(quantity),
            timestamp=_now(),
            metadata=dict(metadata or {}),
        )
        if not event.tenant_id:
            raise ValueError("tenant_id is required.")
        if event.quantity <= 0:
            raise ValueError("quantity must be > 0.")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO meter_events(event_id, tenant_id, metric, quantity, timestamp, metadata_json)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.tenant_id,
                    event.metric,
                    event.quantity,
                    event.timestamp,
                    self._encrypt_metadata(event.tenant_id, event.metadata),
                ),
            )
        return event

    def aggregate(
        self,
        tenant_id: str,
        metric: str,
        period_start: float,
        period_end: float,
    ) -> float:
        """Aggregate one metric total for a billing period.

        Example:
            >>> meter = UsageMeter(path=":memory:")
            >>> meter.aggregate("tenant-a", "agent_runs", 0.0, 1.0)
            0.0
        """

        normalized_metric = str(metric or "").strip()
        if normalized_metric not in SUPPORTED_METRICS:
            raise ValueError(f"Unsupported metric '{metric}'.")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(quantity), 0.0) AS total
                FROM meter_events
                WHERE tenant_id = ? AND metric = ? AND timestamp >= ? AND timestamp < ?
                """,
                (str(tenant_id), normalized_metric, float(period_start), float(period_end)),
            ).fetchone()
        total = float(row["total"] if row else 0.0)
        self._aggregate_history[
            (str(tenant_id), normalized_metric, float(period_start), float(period_end))
        ] = total
        return total

    async def flush_to_stripe(
        self,
        tenant_id: str,
        period_start: float,
        period_end: float,
        *,
        event_sink: EventSink | None = None,
    ) -> list[UsageRecord]:
        """Aggregate all metrics, gate the action, and post usage rows to Stripe.

        Example:
            >>> meter = UsageMeter(path=":memory:")
            >>> rows = __import__("asyncio").run(meter.flush_to_stripe("tenant-a", 0.0, 1.0))
            >>> rows
            []
        """

        aggregates = {
            metric: self.aggregate(tenant_id, metric, period_start, period_end)
            for metric in SUPPORTED_METRICS
        }
        await self.approval_gate.check(
            action="financial_transaction",
            context={
                "tenant_id": tenant_id,
                "period_start": float(period_start),
                "period_end": float(period_end),
                "aggregates": dict(aggregates),
                "event_sink": event_sink,
            },
            action_id=f"meter-flush-{tenant_id}-{int(period_end)}",
        )
        records: list[UsageRecord] = []
        for metric, total in aggregates.items():
            if total <= 0:
                continue
            key = (str(tenant_id), metric, float(period_start), float(period_end))
            if key not in self._aggregate_history:
                raise RuntimeError(
                    f"aggregate() must be called before flush for metric '{metric}'."
                )
            record = await self.stripe_client.create_usage_record(
                self.metric_item_ids.get(metric, f"si_{metric}"),
                total,
                period_end,
            )
            records.append(record)
        return records

    def prune(self, *, max_age_seconds: int) -> int:
        """Delete meter rows older than the age threshold.

        Example:
            >>> meter = UsageMeter(path=":memory:")
            >>> meter.prune(max_age_seconds=3600)
            0
        """

        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be > 0.")
        cutoff = _now() - float(max_age_seconds)
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM meter_events WHERE timestamp < ?", (cutoff,))
        return int(cursor.rowcount)

    def list_events(
        self,
        tenant_id: str,
        *,
        metric: str | None = None,
        period_start: float = 0.0,
        period_end: float | None = None,
    ) -> list[MeterEvent]:
        """List tenant meter rows for one time range.

        Example:
            >>> meter = UsageMeter(path=":memory:")
            >>> meter.list_events("tenant-a")
            []
        """

        end = float(period_end if period_end is not None else _now())
        query = (
            "SELECT event_id, tenant_id, metric, quantity, timestamp, metadata_json "
            "FROM meter_events WHERE tenant_id = ? AND timestamp >= ? AND timestamp < ?"
        )
        params: list[Any] = [str(tenant_id), float(period_start), end]
        if metric:
            query += " AND metric = ?"
            params.append(str(metric))
        query += " ORDER BY timestamp ASC, event_id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [
            MeterEvent(
                event_id=str(row["event_id"]),
                tenant_id=str(row["tenant_id"]),
                metric=str(row["metric"]),
                quantity=float(row["quantity"]),
                timestamp=float(row["timestamp"]),
                metadata=self._decrypt_metadata(str(row["tenant_id"]), str(row["metadata_json"])),
            )
            for row in rows
        ]

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
                CREATE TABLE IF NOT EXISTS meter_events (
                    event_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    timestamp REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_meter_events_tenant_metric_time ON meter_events(tenant_id, metric, timestamp)"
            )

    def _encrypt_metadata(self, tenant_id: str, metadata: dict[str, Any]) -> str:
        if not metadata:
            return "{}"
        key = EncryptionLayer.derive_key(tenant_id, self._master_key)
        payload = EncryptionLayer.encrypt(
            json.dumps(metadata, separators=(",", ":"), sort_keys=True),
            key,
        )
        return json.dumps(
            {
                "ciphertext_b64": payload.ciphertext_b64,
                "nonce_b64": payload.nonce_b64,
                "tag_b64": payload.tag_b64,
            },
            separators=(",", ":"),
        )

    def _decrypt_metadata(self, tenant_id: str, payload: str) -> dict[str, Any]:
        raw = str(payload or "").strip()
        if not raw or raw == "{}":
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        if {"ciphertext_b64", "nonce_b64", "tag_b64"} <= set(parsed):
            key = EncryptionLayer.derive_key(tenant_id, self._master_key)
            try:
                text = EncryptionLayer.decrypt(parsed, key)
            except Exception:
                return {}
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                return {}
            return decoded if isinstance(decoded, dict) else {}
        return parsed
