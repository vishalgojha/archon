"""Append-only mobile sync feed for incremental background refresh."""

from __future__ import annotations

import base64
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class MobileSyncEvent:
    """One mobile sync item.

    Example:
        >>> row = MobileSyncEvent("mob-1", "tenant-a", "approval_required", {}, 1.0)
        >>> row.event_type
        'approval_required'
    """

    event_id: str
    tenant_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event for API responses.

        Example:
            >>> MobileSyncEvent("mob-1", "tenant-a", "approval_required", {}, 1.0).to_dict()["event_id"]
            'mob-1'
        """

        return {
            "event_id": self.event_id,
            "tenant_id": self.tenant_id,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }


@dataclass(slots=True, frozen=True)
class MobileSyncPage:
    """One cursor page returned to the mobile client.

    Example:
        >>> page = MobileSyncPage(events=[], next_cursor=None, has_more=False, watermark=1.0, stale_watermark_recovered=False)
        >>> page.watermark
        1.0
    """

    events: list[MobileSyncEvent]
    next_cursor: str | None
    has_more: bool
    watermark: float
    stale_watermark_recovered: bool


class MobileSyncStore:
    """SQLite-backed append-only sync feed.

    Example:
        >>> store = MobileSyncStore(path="archon/tests/_tmp_mobile_sync_doctest.sqlite3")
        >>> row = store.record_event("tenant-a", "approval_required", {"request_id": "a-1"})
        >>> row.tenant_id
        'tenant-a'
    """

    def __init__(self, path: str | Path = "archon_mobile_sync.sqlite3") -> None:
        """Initialize the feed store.

        Example:
            >>> store = MobileSyncStore(path="archon/tests/_tmp_mobile_sync_init.sqlite3")
            >>> store.path.name.endswith(".sqlite3")
            True
        """

        self.path = Path(path)
        self._init_db()

    def record_event(
        self,
        tenant_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        created_at: float | None = None,
        event_id: str | None = None,
    ) -> MobileSyncEvent:
        """Append one event to the sync feed.

        Example:
            >>> store = MobileSyncStore(path="archon/tests/_tmp_mobile_sync_record.sqlite3")
            >>> row = store.record_event("tenant-a", "approval_required", {"request_id": "a-1"})
            >>> row.event_type
            'approval_required'
        """

        tenant = str(tenant_id or "").strip()
        if not tenant:
            raise ValueError("tenant_id is required.")
        normalized_type = str(event_type or "").strip().lower()
        if not normalized_type:
            raise ValueError("event_type is required.")
        data = dict(payload or {})
        timestamp = float(created_at if created_at is not None else time.time())
        row = MobileSyncEvent(
            event_id=str(event_id or f"mob-{uuid.uuid4().hex[:12]}"),
            tenant_id=tenant,
            event_type=normalized_type,
            payload=data,
            created_at=timestamp,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mobile_sync_events(event_id, tenant_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row.event_id,
                    row.tenant_id,
                    row.event_type,
                    json.dumps(row.payload, separators=(",", ":"), ensure_ascii=True),
                    row.created_at,
                ),
            )
        return row

    def list_events(
        self,
        tenant_id: str,
        *,
        since: float | None = None,
        cursor: str | None = None,
        limit: int = 50,
        max_window_seconds: float = 7 * 24 * 60 * 60,
    ) -> MobileSyncPage:
        """Return one cursor page for a tenant.

        Example:
            >>> store = MobileSyncStore(path="archon/tests/_tmp_mobile_sync_list.sqlite3")
            >>> _ = store.record_event("tenant-a", "approval_required", {"request_id": "a-1"}, created_at=10.0)
            >>> page = store.list_events("tenant-a", since=0.0, limit=10)
            >>> len(page.events)
            1
        """

        tenant = str(tenant_id or "").strip()
        if not tenant:
            return MobileSyncPage([], None, False, 0.0, False)

        bounded = max(1, min(int(limit), 100))
        now = time.time()
        recovered = False
        effective_since = max(0.0, float(since or 0.0))
        if effective_since > now + 60.0 or effective_since < max(0.0, now - max_window_seconds):
            effective_since = max(0.0, now - max_window_seconds)
            recovered = True

        anchor_ts = effective_since
        anchor_id = ""
        decoded = self._decode_cursor(cursor)
        if decoded is not None:
            anchor_ts, anchor_id = decoded

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, tenant_id, event_type, payload_json, created_at
                FROM mobile_sync_events
                WHERE tenant_id = ?
                  AND (
                    created_at > ?
                    OR (created_at = ? AND event_id > ?)
                  )
                ORDER BY created_at ASC, event_id ASC
                LIMIT ?
                """,
                (tenant, anchor_ts, anchor_ts, anchor_id, bounded + 1),
            ).fetchall()

        has_more = len(rows) > bounded
        visible_rows = rows[:bounded]
        events = [
            MobileSyncEvent(
                event_id=str(row["event_id"]),
                tenant_id=str(row["tenant_id"]),
                event_type=str(row["event_type"]),
                payload=_safe_json_dict(str(row["payload_json"])),
                created_at=float(row["created_at"]),
            )
            for row in visible_rows
        ]
        last = events[-1] if events else None
        next_cursor = self._encode_cursor(last.created_at, last.event_id) if last else None
        watermark = last.created_at if last is not None else anchor_ts
        return MobileSyncPage(
            events=events,
            next_cursor=next_cursor,
            has_more=has_more,
            watermark=watermark,
            stale_watermark_recovered=recovered,
        )

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
                CREATE TABLE IF NOT EXISTS mobile_sync_events (
                    event_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_mobile_sync_tenant_time
                ON mobile_sync_events(tenant_id, created_at, event_id)
                """
            )

    @staticmethod
    def _encode_cursor(created_at: float, event_id: str) -> str:
        raw = json.dumps(
            {"created_at": float(created_at), "event_id": str(event_id)},
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii")

    @staticmethod
    def _decode_cursor(cursor: str | None) -> tuple[float, str] | None:
        text = str(cursor or "").strip()
        if not text:
            return None
        try:
            raw = base64.urlsafe_b64decode(text.encode("ascii"))
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        created_at = float(payload.get("created_at") or 0.0)
        event_id = str(payload.get("event_id") or "")
        return created_at, event_id


def _safe_json_dict(payload: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
