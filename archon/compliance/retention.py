"""Data retention and PII anonymization policies for SOC2 workflows."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

ENTITY_TYPES: tuple[str, ...] = (
    "audit_log",
    "session",
    "memory",
    "analytics_event",
    "content_piece",
)
ACTIONS: tuple[str, ...] = ("delete", "anonymize", "archive")


@dataclass(slots=True, frozen=True)
class RetentionRule:
    entity_type: str
    retention_days: int
    action: str


@dataclass(slots=True, frozen=True)
class RetentionResult:
    entity_type: str
    processed_count: int
    action_taken: str


class DataRetentionPolicy:
    """Applies retention rules with optional dry-run preview mode."""

    _TABLE_MAP = {
        "audit_log": "audit_logs",
        "session": "sessions",
        "memory": "episodic_memory",
        "analytics_event": "analytics_events",
        "content_piece": "content_pieces",
    }
    _TIME_COLUMN_MAP = {
        "audit_log": "timestamp",
        "session": "created_at",
        "memory": "timestamp",
        "analytics_event": "timestamp",
        "content_piece": "created_at",
    }

    def __init__(
        self, db_path: str | Path = "archon_compliance.sqlite3", *, dry_run: bool = False
    ) -> None:
        self.db_path = Path(db_path)
        self.dry_run = bool(dry_run)
        self._ensure_schema()

    def apply(self, rule: RetentionRule) -> RetentionResult:
        """Apply one retention rule and return processing summary."""

        entity_type = str(rule.entity_type or "").strip()
        action = str(rule.action or "").strip()
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"Unsupported entity_type '{entity_type}'.")
        if action not in ACTIONS:
            raise ValueError(f"Unsupported action '{action}'.")

        retention_days = max(1, int(rule.retention_days))
        threshold = time.time() - (retention_days * 86400)

        table = self._TABLE_MAP[entity_type]
        time_col = self._TIME_COLUMN_MAP[entity_type]
        if not self._table_exists(table):
            return RetentionResult(
                entity_type=entity_type, processed_count=0, action_taken=self._action_label(action)
            )

        if action == "delete":
            processed = self._delete_older_than(
                table=table, time_column=time_col, threshold=threshold
            )
            return RetentionResult(
                entity_type=entity_type,
                processed_count=processed,
                action_taken=self._action_label(action),
            )

        if action == "anonymize":
            processed = self._anonymize_older_than(
                table=table, time_column=time_col, threshold=threshold
            )
            return RetentionResult(
                entity_type=entity_type,
                processed_count=processed,
                action_taken=self._action_label(action),
            )

        processed = self._archive_older_than(table=table, time_column=time_col, threshold=threshold)
        return RetentionResult(
            entity_type=entity_type,
            processed_count=processed,
            action_taken=self._action_label(action),
        )

    def schedule_all(self, rules: list[RetentionRule]) -> list[RetentionResult]:
        """Apply all retention rules in order."""

        return [self.apply(rule) for rule in rules]

    def _delete_older_than(self, *, table: str, time_column: str, threshold: float) -> int:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE {time_column} < ?",
                (threshold,),
            ).fetchone()
            count = int(row["count"]) if row else 0
            if count and not self.dry_run:
                conn.execute(
                    f"DELETE FROM {table} WHERE {time_column} < ?",
                    (threshold,),
                )
        return count

    def _anonymize_older_than(self, *, table: str, time_column: str, threshold: float) -> int:
        columns = self._table_columns(table)
        pii_columns = [column for column in ("email", "phone", "name") if column in columns]
        if not pii_columns:
            return 0

        select_columns = ", ".join(["rowid", *pii_columns])
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT {select_columns} FROM {table} WHERE {time_column} < ?",
                (threshold,),
            ).fetchall()
            count = len(rows)
            if count == 0 or self.dry_run:
                return count

            for row in rows:
                assignments: list[str] = []
                values: list[str | int] = []
                for column in pii_columns:
                    hashed = _hash_pii(str(row[column] or ""))
                    assignments.append(f"{column} = ?")
                    values.append(hashed)
                values.append(int(row["rowid"]))
                conn.execute(
                    f"UPDATE {table} SET {', '.join(assignments)} WHERE rowid = ?",
                    tuple(values),
                )
        return count

    def _archive_older_than(self, *, table: str, time_column: str, threshold: float) -> int:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE {time_column} < ?",
                (threshold,),
            ).fetchone()
            count = int(row["count"]) if row else 0
            if count == 0 or self.dry_run:
                return count

            columns = self._table_columns(table)
            if "archived" in columns:
                conn.execute(
                    f"UPDATE {table} SET archived = 1 WHERE {time_column} < ?",
                    (threshold,),
                )
        return count

    def _action_label(self, action: str) -> str:
        if self.dry_run:
            return f"dry_run:{action}"
        return action

    def _table_exists(self, table: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
        return row is not None

    def _table_columns(self, table: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row[1]) for row in rows}

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    event_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    name TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    email TEXT,
                    phone TEXT,
                    name TEXT,
                    data_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    memory_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    content TEXT NOT NULL,
                    role TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    embedding_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    forgotten INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analytics_events (
                    event_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    properties_json TEXT NOT NULL DEFAULT '{}',
                    timestamp REAL NOT NULL,
                    session_id TEXT,
                    email TEXT,
                    phone TEXT,
                    name TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_pieces (
                    content_piece_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    name TEXT,
                    archived INTEGER NOT NULL DEFAULT 0
                )
                """
            )


def _hash_pii(value: str) -> str:
    if not value:
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
