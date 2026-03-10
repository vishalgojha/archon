"""SQLite persistence for federation peer + pattern state."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from archon.federation.pattern_sharing import WorkflowPattern
from archon.federation.peer_discovery import Peer


class FederationStore:
    """Persist federation peers and workflow patterns in SQLite.

    Example:
        >>> store = FederationStore(path=":memory:")
        >>> peer = Peer(peer_id="p1", address="https://x", public_key="pk", last_seen=1.0, capabilities=["debate"], version="1.0")
        >>> store.upsert_peer(peer)
        >>> len(store.list_peers())
        1
        >>> store.close()
    """

    def __init__(self, *, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS federation_peers (
                    peer_id TEXT PRIMARY KEY,
                    address TEXT NOT NULL,
                    public_key TEXT NOT NULL,
                    last_seen REAL NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    version TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS federation_patterns (
                    pattern_id TEXT PRIMARY KEY,
                    workflow_type TEXT NOT NULL,
                    step_sequence_json TEXT NOT NULL,
                    avg_score REAL NOT NULL,
                    sample_count INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.commit()

    def upsert_peer(self, peer: Peer) -> None:
        """Insert or update one peer row."""

        payload = asdict(peer)
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO federation_peers
                    (peer_id, address, public_key, last_seen, capabilities_json, version, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(peer_id) DO UPDATE SET
                    address=excluded.address,
                    public_key=excluded.public_key,
                    last_seen=MAX(federation_peers.last_seen, excluded.last_seen),
                    capabilities_json=excluded.capabilities_json,
                    version=excluded.version,
                    updated_at=excluded.updated_at
                """,
                (
                    str(payload["peer_id"]),
                    str(payload["address"]),
                    str(payload["public_key"]),
                    float(payload["last_seen"]),
                    json.dumps(list(payload.get("capabilities") or []), separators=(",", ":")),
                    str(payload["version"]),
                    float(now),
                ),
            )
            self._conn.commit()

    def list_peers(self, *, capability: str | None = None) -> list[Peer]:
        """List stored peers, optionally filtered by capability."""

        capability = str(capability).strip() if capability else None
        query = "SELECT peer_id, address, public_key, last_seen, capabilities_json, version FROM federation_peers"
        params: tuple[Any, ...] = ()
        with self._lock:
            rows = list(self._conn.execute(query, params).fetchall())

        peers: list[Peer] = []
        for peer_id, address, public_key, last_seen, capabilities_json, version in rows:
            try:
                capabilities = json.loads(capabilities_json) if capabilities_json else []
            except Exception:
                capabilities = []
            peer = Peer(
                peer_id=str(peer_id),
                address=str(address),
                public_key=str(public_key),
                last_seen=float(last_seen),
                capabilities=[str(item) for item in (capabilities or [])],
                version=str(version),
            )
            peers.append(peer)
        if capability:
            peers = [peer for peer in peers if capability in peer.capabilities]
        peers.sort(key=lambda row: row.last_seen, reverse=True)
        return peers

    def upsert_pattern(self, pattern: WorkflowPattern) -> None:
        """Insert or update one workflow pattern row."""

        payload = asdict(pattern)
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO federation_patterns
                    (pattern_id, workflow_type, step_sequence_json, avg_score, sample_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(pattern_id) DO UPDATE SET
                    workflow_type=excluded.workflow_type,
                    step_sequence_json=excluded.step_sequence_json,
                    avg_score=excluded.avg_score,
                    sample_count=excluded.sample_count,
                    updated_at=excluded.updated_at
                """,
                (
                    str(payload["pattern_id"]),
                    str(payload["workflow_type"]),
                    json.dumps(list(payload.get("step_sequence") or []), separators=(",", ":")),
                    float(payload["avg_score"]),
                    int(payload["sample_count"]),
                    float(now),
                ),
            )
            self._conn.commit()

    def list_patterns(self, *, limit: int = 50) -> list[WorkflowPattern]:
        """List stored workflow patterns, sorted by sample_count desc."""

        limit = max(1, min(int(limit), 500))
        query = """
            SELECT pattern_id, workflow_type, step_sequence_json, avg_score, sample_count
            FROM federation_patterns
            ORDER BY sample_count DESC, updated_at DESC
            LIMIT ?
        """
        with self._lock:
            rows = list(self._conn.execute(query, (limit,)).fetchall())
        patterns: list[WorkflowPattern] = []
        for pattern_id, workflow_type, step_sequence_json, avg_score, sample_count in rows:
            try:
                steps = json.loads(step_sequence_json) if step_sequence_json else []
            except Exception:
                steps = []
            patterns.append(
                WorkflowPattern(
                    pattern_id=str(pattern_id),
                    workflow_type=str(workflow_type),
                    step_sequence=[str(item) for item in (steps or [])],
                    avg_score=float(avg_score),
                    sample_count=int(sample_count),
                )
            )
        return patterns
