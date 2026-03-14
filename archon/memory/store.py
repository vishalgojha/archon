"""Tenant-isolated episodic and causal memory store."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archon.memory.embedder import Embedder
from archon.memory.vector_index import VectorIndex


@dataclass(slots=True, frozen=True)
class EpisodicMemory:
    """One episodic memory record."""

    memory_id: str
    timestamp: float
    content: str
    role: str
    session_id: str
    tenant_id: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class CausalChain:
    """One causal relation record."""

    chain_id: str
    event: str
    cause: str
    effect: str
    confidence: float
    supporting_memory_ids: list[str]
    timestamp: float


@dataclass(slots=True, frozen=True)
class ScoredMemory:
    """Search hit containing memory with similarity score."""

    memory: EpisodicMemory
    similarity: float


class MemoryStore:
    """Main interface for ARCHON memory operations."""

    def __init__(
        self,
        *,
        db_path: str = "archon_memory.sqlite3",
        embedder: Embedder | None = None,
        vector_index: VectorIndex | None = None,
    ) -> None:
        self.db_path = db_path
        self.embedder = embedder or Embedder(db_path=db_path)
        self.vector_index = vector_index or VectorIndex()
        self._ensure_schema()
        self._hydrate_vector_index()

    def close(self) -> None:
        """Close resources owned by store."""

        close_method = getattr(self.embedder, "close", None)
        if callable(close_method):
            close_method()

    def add(
        self,
        content: str,
        role: str,
        session_id: str,
        tenant_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> EpisodicMemory:
        """Add memory entry with automatic embedding."""

        now = time.time()
        memory_id = f"mem-{uuid.uuid4().hex[:12]}"
        vector = self.embedder.embed(content)
        memory = EpisodicMemory(
            memory_id=memory_id,
            timestamp=now,
            content=str(content),
            role=str(role),
            session_id=str(session_id),
            tenant_id=str(tenant_id),
            embedding=list(vector),
            metadata=dict(metadata or {}),
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO episodic_memory (
                    memory_id, timestamp, content, role, session_id, tenant_id, embedding_json,
                    metadata_json, forgotten
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    memory.memory_id,
                    memory.timestamp,
                    memory.content,
                    memory.role,
                    memory.session_id,
                    memory.tenant_id,
                    json.dumps(memory.embedding, separators=(",", ":")),
                    json.dumps(memory.metadata, separators=(",", ":")),
                ),
            )
            conn.commit()

        self.vector_index.add(
            id=memory.memory_id,
            vector=memory.embedding,
            metadata={
                "tenant_id": memory.tenant_id,
                "session_id": memory.session_id,
                "role": memory.role,
                "forgotten": False,
            },
        )
        return memory

    def search(
        self, query: str, tenant_id: str, top_k: int = 10, min_similarity: float = 0.7
    ) -> list[ScoredMemory]:
        """Search memories by semantic similarity with strict tenant isolation."""

        query_vector = self.embedder.embed(query)
        raw_hits = self.vector_index.search(
            query_vector=query_vector,
            top_k=max(top_k, self.vector_index.count if self.vector_index.count > 0 else top_k),
            min_similarity=min_similarity,
        )
        memory_ids = [
            hit.id
            for hit in raw_hits
            if str(hit.metadata.get("tenant_id")) == tenant_id
            and not bool(hit.metadata.get("forgotten"))
        ]
        memory_map = self._fetch_memories(memory_ids, tenant_id=tenant_id)
        scored: list[ScoredMemory] = []
        for hit in raw_hits:
            memory = memory_map.get(hit.id)
            if memory is None:
                continue
            scored.append(ScoredMemory(memory=memory, similarity=hit.similarity))
            if len(scored) >= top_k:
                break
        return scored

    def add_causal_link(
        self,
        cause_event: str,
        effect_event: str,
        confidence: float,
        supporting_ids: list[str],
        *,
        tenant_id: str | None = None,
    ) -> CausalChain:
        """Store a directed cause->effect relationship."""

        chain = CausalChain(
            chain_id=f"chain-{uuid.uuid4().hex[:12]}",
            event=str(effect_event),
            cause=str(cause_event),
            effect=str(effect_event),
            confidence=max(0.0, min(1.0, float(confidence))),
            supporting_memory_ids=[str(item) for item in supporting_ids],
            timestamp=time.time(),
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO causal_chains (
                    chain_id, event, cause, effect, confidence, supporting_memory_ids_json, timestamp, tenant_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chain.chain_id,
                    chain.event,
                    chain.cause,
                    chain.effect,
                    chain.confidence,
                    json.dumps(chain.supporting_memory_ids, separators=(",", ":")),
                    chain.timestamp,
                    tenant_id,
                ),
            )
            conn.commit()
        return chain

    def get_causal_chain(
        self, event_description: str, depth: int = 3, *, tenant_id: str | None = None
    ) -> list[CausalChain]:
        """Traverse causal links from cause to downstream effects up to depth."""

        frontier = [str(event_description)]
        visited: set[str] = set()
        output: list[CausalChain] = []
        depth = max(1, int(depth))
        for _ in range(depth):
            if not frontier:
                break
            placeholders = ",".join(["?"] * len(frontier))
            params: list[Any] = list(frontier)
            where = f"cause IN ({placeholders})"
            if tenant_id is not None:
                where += " AND tenant_id = ?"
                params.append(tenant_id)
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    f"""
                    SELECT chain_id, event, cause, effect, confidence, supporting_memory_ids_json, timestamp
                    FROM causal_chains
                    WHERE {where}
                    ORDER BY timestamp ASC
                    """,
                    tuple(params),
                ).fetchall()
            next_frontier: list[str] = []
            for row in rows:
                chain = _chain_from_row(row)
                if chain.chain_id in visited:
                    continue
                visited.add(chain.chain_id)
                output.append(chain)
                next_frontier.append(chain.effect)
            frontier = next_frontier
        return output

    def get_session_context(
        self, session_id: str, last_n: int = 20, *, tenant_id: str | None = None
    ) -> list[EpisodicMemory]:
        """Return most recent session memories (non-forgotten)."""

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            params: list[Any] = [str(session_id)]
            where = "session_id = ? AND forgotten = 0"
            if tenant_id is not None:
                where += " AND tenant_id = ?"
                params.append(tenant_id)
            rows = conn.execute(
                f"""
                SELECT memory_id, timestamp, content, role, session_id, tenant_id, embedding_json, metadata_json
                FROM episodic_memory
                WHERE {where}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                tuple(params + [max(1, int(last_n))]),
            ).fetchall()
        return [_memory_from_row(row) for row in rows]

    def forget(self, memory_id: str) -> None:
        """Soft-delete memory by marking forgotten and dropping from active index."""

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE episodic_memory SET forgotten = 1 WHERE memory_id = ?",
                (str(memory_id),),
            )
            conn.commit()
        self.vector_index.delete(str(memory_id))

    def export_tenant(
        self,
        tenant_id: str,
        output_path: str,
        *,
        include_forgotten: bool = False,
        limit: int | None = None,
    ) -> int:
        """Export tenant memories to JSONL and return row count."""

        where = "tenant_id = ?"
        params: list[Any] = [str(tenant_id)]
        if not include_forgotten:
            where += " AND forgotten = 0"
        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT ?"
            params.append(max(1, int(limit)))

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT memory_id, timestamp, content, role, session_id, tenant_id,
                       embedding_json, metadata_json, forgotten
                FROM episodic_memory
                WHERE {where}
                ORDER BY timestamp ASC
                {limit_clause}
                """,
                tuple(params),
            ).fetchall()

        path = str(output_path)
        count = 0
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                payload = _memory_export_payload(row)
                handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
                count += 1
        return count

    def import_tenant(
        self,
        tenant_id: str,
        input_path: str,
        *,
        allow_tenant_mismatch: bool = False,
        on_conflict: str = "skip",
        limit: int | None = None,
    ) -> dict[str, int]:
        """Import tenant memories from a JSONL export.

        The import preserves embedding vectors when present and updates the in-memory
        vector index for non-forgotten entries.
        """

        source_path = Path(str(input_path))
        if not source_path.exists():
            raise FileNotFoundError(str(source_path))
        if on_conflict not in {"skip", "overwrite"}:
            raise ValueError("on_conflict must be 'skip' or 'overwrite'.")

        imported = 0
        skipped = 0
        replaced = 0
        seen = 0
        with source_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if limit is not None and seen >= int(limit):
                    break
                raw = line.strip()
                if not raw:
                    continue
                seen += 1
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                if not isinstance(payload, dict):
                    skipped += 1
                    continue
                outcome = self.import_entries(
                    tenant_id=tenant_id,
                    entries=[payload],
                    allow_tenant_mismatch=allow_tenant_mismatch,
                    on_conflict=on_conflict,
                )
                imported += outcome["imported"]
                replaced += outcome["replaced"]
                skipped += outcome["skipped"]

        return {"imported": imported, "replaced": replaced, "skipped": skipped}

    def import_entries(
        self,
        *,
        tenant_id: str,
        entries: list[dict[str, Any]],
        allow_tenant_mismatch: bool = False,
        on_conflict: str = "skip",
    ) -> dict[str, int]:
        """Import a list of exported memory payloads into the tenant namespace."""

        if on_conflict not in {"skip", "overwrite"}:
            raise ValueError("on_conflict must be 'skip' or 'overwrite'.")
        imported = 0
        skipped = 0
        replaced = 0
        for payload in entries:
            ok, outcome = self._import_one(
                tenant_id=str(tenant_id),
                payload=payload,
                allow_tenant_mismatch=bool(allow_tenant_mismatch),
                on_conflict=str(on_conflict),
            )
            if not ok:
                skipped += 1
                continue
            imported += 1
            if outcome == "replaced":
                replaced += 1
        return {"imported": imported, "replaced": replaced, "skipped": skipped}

    def _import_one(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
        allow_tenant_mismatch: bool,
        on_conflict: str,
    ) -> tuple[bool, str]:
        memory_id = str(payload.get("memory_id") or "").strip() or f"mem-{uuid.uuid4().hex[:12]}"
        content = str(payload.get("content") or "")
        role = str(payload.get("role") or "assistant")
        session_id = str(payload.get("session_id") or "session-import")
        timestamp = float(payload.get("timestamp") or time.time())
        source_tenant = str(payload.get("tenant_id") or "").strip()
        forgotten = bool(payload.get("forgotten", False))
        metadata = payload.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}

        if source_tenant and source_tenant != tenant_id:
            if not allow_tenant_mismatch:
                return False, "skipped"
            metadata = dict(metadata)
            metadata.setdefault("source_tenant_id", source_tenant)

        embedding = payload.get("embedding", [])
        embedding = embedding if isinstance(embedding, list) else []
        vector: list[float] = []
        for item in embedding:
            try:
                vector.append(float(item))
            except (TypeError, ValueError):
                vector = []
                break
        if not vector:
            dim = int(getattr(self.embedder, "default_dim", 768) or 768)
            vector = [0.0 for _ in range(max(1, dim))]

        replaced = False
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT 1 FROM episodic_memory WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            exists = row is not None
            if exists and on_conflict == "skip":
                return False, "skipped"
            conn.execute(
                """
                INSERT INTO episodic_memory (
                    memory_id, timestamp, content, role, session_id, tenant_id, embedding_json,
                    metadata_json, forgotten
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    timestamp=excluded.timestamp,
                    content=excluded.content,
                    role=excluded.role,
                    session_id=excluded.session_id,
                    tenant_id=excluded.tenant_id,
                    embedding_json=excluded.embedding_json,
                    metadata_json=excluded.metadata_json,
                    forgotten=excluded.forgotten
                """,
                (
                    memory_id,
                    timestamp,
                    content,
                    role,
                    session_id,
                    tenant_id,
                    json.dumps(vector, separators=(",", ":")),
                    json.dumps(metadata, separators=(",", ":")),
                    1 if forgotten else 0,
                ),
            )
            conn.commit()
            replaced = bool(exists)

        if forgotten:
            self.vector_index.delete(memory_id)
        else:
            self.vector_index.add(
                id=memory_id,
                vector=vector,
                metadata={
                    "tenant_id": tenant_id,
                    "session_id": session_id,
                    "role": role,
                    "forgotten": False,
                },
            )

        return True, "replaced" if replaced else "imported"

    def _ensure_schema(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    memory_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    content TEXT NOT NULL,
                    role TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    forgotten INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodic_tenant ON episodic_memory(tenant_id, forgotten)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS causal_chains (
                    chain_id TEXT PRIMARY KEY,
                    event TEXT NOT NULL,
                    cause TEXT NOT NULL,
                    effect TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    supporting_memory_ids_json TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    tenant_id TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_causal_cause ON causal_chains(cause, timestamp)"
            )
            conn.commit()

    def _hydrate_vector_index(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT memory_id, embedding_json, tenant_id, session_id, role
                FROM episodic_memory
                WHERE forgotten = 0
                """
            ).fetchall()
        for row in rows:
            vector = _safe_json_list(row["embedding_json"])
            self.vector_index.add(
                id=row["memory_id"],
                vector=vector,
                metadata={
                    "tenant_id": row["tenant_id"],
                    "session_id": row["session_id"],
                    "role": row["role"],
                    "forgotten": False,
                },
            )

    def _fetch_memories(
        self, memory_ids: list[str], *, tenant_id: str
    ) -> dict[str, EpisodicMemory]:
        if not memory_ids:
            return {}
        placeholders = ",".join(["?"] * len(memory_ids))
        params = [tenant_id, *memory_ids]
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT memory_id, timestamp, content, role, session_id, tenant_id, embedding_json, metadata_json
                FROM episodic_memory
                WHERE tenant_id = ? AND forgotten = 0 AND memory_id IN ({placeholders})
                """,
                tuple(params),
            ).fetchall()
        return {row["memory_id"]: _memory_from_row(row) for row in rows}


def _memory_from_row(row: sqlite3.Row) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=row["memory_id"],
        timestamp=float(row["timestamp"]),
        content=row["content"],
        role=row["role"],
        session_id=row["session_id"],
        tenant_id=row["tenant_id"],
        embedding=_safe_json_list(row["embedding_json"]),
        metadata=_safe_json_dict(row["metadata_json"]),
    )


def _memory_export_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "memory_id": row["memory_id"],
        "timestamp": float(row["timestamp"]),
        "content": row["content"],
        "role": row["role"],
        "session_id": row["session_id"],
        "tenant_id": row["tenant_id"],
        "embedding": _safe_json_list(row["embedding_json"]),
        "metadata": _safe_json_dict(row["metadata_json"]),
        "forgotten": bool(row["forgotten"]),
    }


def _chain_from_row(row: sqlite3.Row) -> CausalChain:
    return CausalChain(
        chain_id=row["chain_id"],
        event=row["event"],
        cause=row["cause"],
        effect=row["effect"],
        confidence=float(row["confidence"]),
        supporting_memory_ids=[
            str(item) for item in _safe_json_list(row["supporting_memory_ids_json"])
        ],
        timestamp=float(row["timestamp"]),
    )


def _safe_json_list(payload: str) -> list[Any]:
    try:
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _safe_json_dict(payload: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}
