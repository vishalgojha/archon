"""Immutable SQLite-backed audit trail with hash-chain integrity."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "skill_proposed",
        "skill_promoted",
        "skill_rolled_back",
        "skill_trial_completed",
        "task_completed",
        "task_failed",
        "workflow_created",
        "workflow_staged",
        "workflow_promoted",
        "workflow_rolled_back",
        "trial_completed",
    }
)


@dataclass(slots=True, frozen=True)
class AuditEntry:
    """One immutable audit event row."""

    entry_id: str
    timestamp: float
    event_type: str
    workflow_id: str
    actor: str
    payload: dict[str, Any]
    prev_hash: str
    entry_hash: str


class ImmutableAuditTrail:
    """Append-only audit trail with chained SHA-256 hashes."""

    def __init__(self, db_path: str = "archon_evolution_audit.sqlite3") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def close(self) -> None:
        """Close SQLite connection resources."""

        with self._lock:
            self._conn.close()

    def append(self, entry: AuditEntry) -> AuditEntry:
        """Append one audit event and return the persisted entry."""

        with self._lock:
            if entry.event_type not in VALID_EVENT_TYPES:
                raise ValueError(f"Unsupported audit event_type: {entry.event_type}")

            prev_hash = self._last_hash()
            if entry.prev_hash and entry.prev_hash != prev_hash:
                raise ValueError("entry.prev_hash does not match current chain tail.")

            payload_json = _payload_json(entry.payload)
            computed_hash = _compute_entry_hash(
                prev_hash=prev_hash,
                entry_id=entry.entry_id,
                timestamp=entry.timestamp,
                payload_json=payload_json,
            )
            if entry.entry_hash and entry.entry_hash != computed_hash:
                raise ValueError("entry.entry_hash does not match computed hash.")

            persisted = AuditEntry(
                entry_id=entry.entry_id,
                timestamp=float(entry.timestamp),
                event_type=entry.event_type,
                workflow_id=entry.workflow_id,
                actor=entry.actor,
                payload=dict(entry.payload),
                prev_hash=prev_hash,
                entry_hash=computed_hash,
            )
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO audit_entries (
                        entry_id, timestamp, event_type, workflow_id, actor,
                        payload_json, prev_hash, entry_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        persisted.entry_id,
                        persisted.timestamp,
                        persisted.event_type,
                        persisted.workflow_id,
                        persisted.actor,
                        payload_json,
                        persisted.prev_hash,
                        persisted.entry_hash,
                    ),
                )
            return persisted

    def get_history(self, workflow_id: str) -> list[AuditEntry]:
        """Return chronological history for one workflow."""

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT entry_id, timestamp, event_type, workflow_id, actor, payload_json, prev_hash, entry_hash
                FROM audit_entries
                WHERE workflow_id = ?
                ORDER BY seq ASC
                """,
                (workflow_id,),
            ).fetchall()
            return [_row_to_entry(row) for row in rows]

    def get_recent_entries(
        self,
        *,
        limit: int = 50,
        event_types: list[str] | None = None,
    ) -> list[AuditEntry]:
        """Return most recent entries, optionally filtered by event type."""

        event_filter = None
        if event_types:
            event_filter = [str(item) for item in event_types if str(item).strip()]
        with self._lock:
            if event_filter:
                placeholders = ",".join("?" for _ in event_filter)
                rows = self._conn.execute(
                    f"""
                    SELECT entry_id, timestamp, event_type, workflow_id, actor, payload_json, prev_hash, entry_hash
                    FROM audit_entries
                    WHERE event_type IN ({placeholders})
                    ORDER BY seq DESC
                    LIMIT ?
                    """,
                    (*event_filter, int(limit)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT entry_id, timestamp, event_type, workflow_id, actor, payload_json, prev_hash, entry_hash
                    FROM audit_entries
                    ORDER BY seq DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
            return [_row_to_entry(row) for row in rows]

    def verify_integrity(self) -> bool:
        """Recompute hash chain and validate stored links."""

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT entry_id, timestamp, payload_json, prev_hash, entry_hash
                FROM audit_entries
                ORDER BY seq ASC
                """
            ).fetchall()
            expected_prev_hash = ""
            for row in rows:
                if row["prev_hash"] != expected_prev_hash:
                    return False
                computed = _compute_entry_hash(
                    prev_hash=row["prev_hash"],
                    entry_id=row["entry_id"],
                    timestamp=float(row["timestamp"]),
                    payload_json=row["payload_json"],
                )
                if computed != row["entry_hash"]:
                    return False
                expected_prev_hash = row["entry_hash"]
            return True

    def export_chain(self, path: str | Path) -> Path:
        """Export full chain to JSONL."""

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT entry_id, timestamp, event_type, workflow_id, actor, payload_json, prev_hash, entry_hash
                FROM audit_entries
                ORDER BY seq ASC
                """
            ).fetchall()
            lines = []
            for row in rows:
                payload = {
                    "entry_id": row["entry_id"],
                    "timestamp": float(row["timestamp"]),
                    "event_type": row["event_type"],
                    "workflow_id": row["workflow_id"],
                    "actor": row["actor"],
                    "payload": json.loads(row["payload_json"]),
                    "prev_hash": row["prev_hash"],
                    "entry_hash": row["entry_hash"],
                }
                lines.append(json.dumps(payload, separators=(",", ":")))
        output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return output_path

    def _ensure_schema(self) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_entries (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        entry_id TEXT NOT NULL UNIQUE,
                        timestamp REAL NOT NULL,
                        event_type TEXT NOT NULL,
                        workflow_id TEXT NOT NULL,
                        actor TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        prev_hash TEXT NOT NULL,
                        entry_hash TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_workflow_id ON audit_entries(workflow_id)"
                )

    def _last_hash(self) -> str:
        row = self._conn.execute(
            "SELECT entry_hash FROM audit_entries ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return str(row["entry_hash"]) if row is not None else ""


def _compute_entry_hash(
    *, prev_hash: str, entry_id: str, timestamp: float, payload_json: str
) -> str:
    base = f"{prev_hash}{entry_id}{timestamp}{payload_json}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _payload_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _row_to_entry(row: sqlite3.Row) -> AuditEntry:
    return AuditEntry(
        entry_id=row["entry_id"],
        timestamp=float(row["timestamp"]),
        event_type=row["event_type"],
        workflow_id=row["workflow_id"],
        actor=row["actor"],
        payload=json.loads(row["payload_json"]),
        prev_hash=row["prev_hash"],
        entry_hash=row["entry_hash"],
    )
