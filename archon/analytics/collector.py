"""Analytics event collector with append-only SQLite persistence."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

ANALYTICS_EVENT_TYPES: tuple[str, ...] = (
    "task_completed",
    "approval_requested",
    "approval_granted",
    "approval_denied",
    "auth_session_token_issued",
    "ui_pack_build",
    "ui_pack_publish",
    "ui_pack_activate",
    "state_change",
    "workflow_created",
    "workflow_staged",
    "workflow_rolled_back",
)


@dataclass(slots=True, frozen=True)
class AnalyticsEvent:
    """Immutable analytics event row."""

    event_id: str
    tenant_id: str
    event_type: str
    properties: dict[str, Any]
    timestamp: float


class AnalyticsCollector:
    """Append-only analytics event collector backed by SQLite."""

    def __init__(self, path: str | Path = "archon_analytics.sqlite3") -> None:
        self.path = Path(path)
        self._init_db()

    def record(self, tenant_id: str, event_type: str, properties: dict[str, Any]) -> AnalyticsEvent:
        """Record one analytics event and return the persisted row."""

        row = self._coerce_event(
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "properties": dict(properties or {}),
            }
        )
        self._insert_many([row])
        return row

    def batch_record(self, events: list[dict[str, Any] | AnalyticsEvent]) -> list[AnalyticsEvent]:
        """Record multiple events in one transaction."""

        rows = [self._coerce_event(item) for item in events]
        if rows:
            self._insert_many(rows)
        return rows

    def list_events(
        self,
        tenant_id: str,
        *,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[AnalyticsEvent]:
        """List raw events for one tenant in reverse-chronological order."""

        tenant = str(tenant_id or "").strip()
        if not tenant:
            return []
        bounded = max(1, min(int(limit), 1000))

        query = (
            "SELECT event_id, tenant_id, event_type, properties_json, timestamp "
            "FROM analytics_events WHERE tenant_id = ?"
        )
        params: list[Any] = [tenant]
        if event_type:
            normalized = str(event_type).strip().lower()
            query += " AND event_type = ?"
            params.append(normalized)
        query += " ORDER BY timestamp DESC, event_id DESC LIMIT ?"
        params.append(bounded)

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, tuple(params)).fetchall()

        return [
            AnalyticsEvent(
                event_id=str(row["event_id"]),
                tenant_id=str(row["tenant_id"]),
                event_type=str(row["event_type"]),
                properties=_safe_json_dict(str(row["properties_json"])),
                timestamp=float(row["timestamp"]),
            )
            for row in rows
        ]

    def _coerce_event(self, item: dict[str, Any] | AnalyticsEvent) -> AnalyticsEvent:
        if isinstance(item, AnalyticsEvent):
            self._validate_event_type(item.event_type)
            if not str(item.tenant_id).strip():
                raise ValueError("tenant_id is required.")
            return item

        tenant_id = str(item.get("tenant_id", "")).strip()
        if not tenant_id:
            raise ValueError("tenant_id is required.")

        event_type = str(item.get("event_type", "")).strip().lower()
        self._validate_event_type(event_type)

        properties_raw = item.get("properties", {})
        if not isinstance(properties_raw, dict):
            raise ValueError("properties must be a dict.")
        properties = dict(properties_raw)

        timestamp_raw = item.get("timestamp", properties.pop("timestamp", None))
        timestamp = float(timestamp_raw) if timestamp_raw is not None else time.time()

        event_id = str(item.get("event_id") or f"evt-{uuid.uuid4().hex[:12]}")
        return AnalyticsEvent(
            event_id=event_id,
            tenant_id=tenant_id,
            event_type=event_type,
            properties=properties,
            timestamp=timestamp,
        )

    def _insert_many(self, rows: list[AnalyticsEvent]) -> None:
        with self._connect() as conn:
            for row in rows:
                session_id = str(row.properties.get("session_id", "")).strip() or None
                conn.execute(
                    """
                    INSERT INTO analytics_events(event_id, tenant_id, event_type, properties_json, timestamp, session_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.event_id,
                        row.tenant_id,
                        row.event_type,
                        json.dumps(row.properties, separators=(",", ":")),
                        row.timestamp,
                        session_id,
                    ),
                )

    @staticmethod
    def _validate_event_type(event_type: str) -> None:
        if event_type not in ANALYTICS_EVENT_TYPES:
            raise ValueError(f"Unsupported event_type '{event_type}'.")

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
                CREATE TABLE IF NOT EXISTS analytics_events (
                    event_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    properties_json TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    session_id TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_analytics_tenant_time ON analytics_events(tenant_id, timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_analytics_tenant_type ON analytics_events(tenant_id, event_type, timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_analytics_tenant_session ON analytics_events(tenant_id, session_id, timestamp)"
            )


def _safe_json_dict(payload: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
