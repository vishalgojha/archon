"""Causal episodic memory storage (SQLite-backed)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any


class MemoryStore:
    """Stores causal task memory entries in local SQLite.

    Example:
        >>> await store.add_entry(task="X", context={}, actions_taken=[], causal_reasoning="...", actual_outcome="...", delta="...", reuse_conditions="...")
        >>> entries = await store.list_recent(limit=5)
    """

    def __init__(self, db_path: str | Path = "archon_memory.sqlite3") -> None:
        self.db_path = str(db_path)
        self._initialized = False

    async def initialize(self) -> None:
        """Create memory tables if they do not exist."""

        if self._initialized:
            return
        await asyncio.to_thread(self._initialize_sync)
        self._initialized = True

    async def add_entry(
        self,
        *,
        task: str,
        context: dict[str, Any],
        actions_taken: list[str],
        causal_reasoning: str,
        actual_outcome: str,
        delta: str,
        reuse_conditions: str,
    ) -> int:
        """Persist one causal memory entry.

        Example:
            >>> entry_id = await store.add_entry(...)
            >>> entry_id > 0
            True
        """

        await self.initialize()
        return await asyncio.to_thread(
            self._insert_sync,
            task,
            json.dumps(context),
            json.dumps(actions_taken),
            causal_reasoning,
            actual_outcome,
            delta,
            reuse_conditions,
        )

    async def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent memory entries for operator visibility.

        Example:
            >>> rows = await store.list_recent(limit=10)
            >>> isinstance(rows, list)
            True
        """

        await self.initialize()
        return await asyncio.to_thread(self._list_recent_sync, limit)

    def _initialize_sync(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    actions_taken_json TEXT NOT NULL,
                    causal_reasoning TEXT NOT NULL,
                    actual_outcome TEXT NOT NULL,
                    delta TEXT NOT NULL,
                    reuse_conditions TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _insert_sync(
        self,
        task: str,
        context_json: str,
        actions_taken_json: str,
        causal_reasoning: str,
        actual_outcome: str,
        delta: str,
        reuse_conditions: str,
    ) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                INSERT INTO memory_entries (
                    task, context_json, actions_taken_json, causal_reasoning,
                    actual_outcome, delta, reuse_conditions
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task,
                    context_json,
                    actions_taken_json,
                    causal_reasoning,
                    actual_outcome,
                    delta,
                    reuse_conditions,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def _list_recent_sync(self, limit: int) -> list[dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT id, task, context_json, actions_taken_json, causal_reasoning,
                       actual_outcome, delta, reuse_conditions, created_at
                FROM memory_entries
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            output: list[dict[str, Any]] = []
            for row in rows:
                output.append(
                    {
                        "id": row["id"],
                        "task": row["task"],
                        "context": json.loads(row["context_json"]),
                        "actions_taken": json.loads(row["actions_taken_json"]),
                        "causal_reasoning": row["causal_reasoning"],
                        "actual_outcome": row["actual_outcome"],
                        "delta": row["delta"],
                        "reuse_conditions": row["reuse_conditions"],
                        "created_at": row["created_at"],
                    }
                )
            return output
        finally:
            conn.close()

