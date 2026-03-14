"""Session and message storage backends for webchat runtime."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Iterator

DEFAULT_SQLITE_PATH = "archon_webchat.sqlite3"
MAX_HISTORY_MESSAGES = 200


def _now() -> float:
    return time.time()


def _message_id() -> str:
    return f"msg-{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class Message:
    """One chat message.

    Example:
        >>> msg = Message(session_id="s1", role="user", content="hello")
        >>> msg.id.startswith("msg-")
        True
    """

    session_id: str
    role: str
    content: str
    id: str = field(default_factory=_message_id)
    created_at: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize message for wire/storage.

        Example:
            >>> Message(session_id="s1", role="user", content="x").to_dict()["role"]
            'user'
        """

        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Message":
        """Hydrate from serialized form.

        Example:
            >>> Message.from_dict({"id":"m","session_id":"s1","role":"user","content":"x","created_at":1.0})
            Message(session_id='s1', role='user', content='x', id='m', created_at=1.0, metadata={})
        """

        return cls(
            id=str(payload.get("id") or _message_id()),
            session_id=str(payload.get("session_id", "")).strip(),
            role=str(payload.get("role", "user")).strip() or "user",
            content=str(payload.get("content", "")),
            created_at=float(payload.get("created_at", _now())),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class SessionState:
    """Mutable session metadata.

    Example:
        >>> state = SessionState(session_id="s1", tenant_id="anon:abc123def456", tier="free")
        >>> state.session_id
        's1'
    """

    session_id: str
    tenant_id: str
    tier: str
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for wire/storage.

        Example:
            >>> SessionState("s1","t1","free").to_dict()["tier"]
            'free'
        """

        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "tier": self.tier,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionState":
        """Hydrate from serialized form.

        Example:
            >>> SessionState.from_dict({"session_id":"s1","tenant_id":"t1","tier":"free"}).tenant_id
            't1'
        """

        return cls(
            session_id=str(payload.get("session_id", "")).strip(),
            tenant_id=str(payload.get("tenant_id", "")).strip(),
            tier=str(payload.get("tier", "free")).strip() or "free",
            created_at=float(payload.get("created_at", _now())),
            updated_at=float(payload.get("updated_at", _now())),
            metadata=dict(payload.get("metadata") or {}),
        )


class AbstractSessionStore(ABC):
    """Contract for session storage backends."""

    @abstractmethod
    async def create_session(self, session: SessionState) -> SessionState:
        """Create one session row.

        Example:
            >>> # await store.create_session(SessionState("s1","t1","free"))
            >>> True
            True
        """

    @abstractmethod
    async def get_session(self, session_id: str) -> SessionState | None:
        """Load session by id.

        Example:
            >>> # await store.get_session("s1")
            >>> True
            True
        """

    @abstractmethod
    async def update_session(self, session: SessionState) -> SessionState:
        """Update one existing session row.

        Example:
            >>> # await store.update_session(SessionState("s1","t1","free"))
            >>> True
            True
        """

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        """Delete one session row.

        Example:
            >>> # await store.delete_session("s1")
            >>> True
            True
        """

    @abstractmethod
    async def append_message(self, session_id: str, message: Message) -> Message:
        """Append one message to a session.

        Example:
            >>> # await store.append_message("s1", Message("s1","user","hello"))
            >>> True
            True
        """

    @abstractmethod
    async def get_messages(self, session_id: str, *, last_n: int | None = None) -> list[Message]:
        """Read ordered messages for one session.

        Example:
            >>> # await store.get_messages("s1", last_n=10)
            >>> True
            True
        """

    @abstractmethod
    async def clear_messages(self, session_id: str) -> int:
        """Delete all messages for one session.

        Example:
            >>> # await store.clear_messages("s1")
            >>> True
            True
        """


class InMemorySessionStore(AbstractSessionStore):
    """In-memory session store for tests and ephemeral deployments."""

    def __init__(self, *, max_history_messages: int = MAX_HISTORY_MESSAGES) -> None:
        """Initialize empty in-memory store.

        Example:
            >>> store = InMemorySessionStore(max_history_messages=10)
            >>> isinstance(store, InMemorySessionStore)
            True
        """

        if max_history_messages <= 0:
            raise ValueError("max_history_messages must be > 0.")
        self.max_history_messages = max_history_messages
        self._sessions: dict[str, SessionState] = {}
        self._messages: dict[str, list[Message]] = {}
        self._lock = Lock()

    async def create_session(self, session: SessionState) -> SessionState:
        """Create one session row.

        Example:
            >>> # await InMemorySessionStore().create_session(SessionState("s","t","free"))
            >>> True
            True
        """

        with self._lock:
            clone = SessionState.from_dict(session.to_dict())
            clone.updated_at = _now()
            self._sessions[clone.session_id] = clone
            self._messages.setdefault(clone.session_id, [])
            return SessionState.from_dict(clone.to_dict())

    async def get_session(self, session_id: str) -> SessionState | None:
        """Load one session by id.

        Example:
            >>> # await InMemorySessionStore().get_session("missing")
            >>> True
            True
        """

        with self._lock:
            row = self._sessions.get(session_id)
            return SessionState.from_dict(row.to_dict()) if row else None

    async def update_session(self, session: SessionState) -> SessionState:
        """Update one existing session row.

        Example:
            >>> # await InMemorySessionStore().update_session(SessionState("s","t","free"))
            >>> True
            True
        """

        with self._lock:
            if session.session_id not in self._sessions:
                raise KeyError(f"Session '{session.session_id}' not found.")
            clone = SessionState.from_dict(session.to_dict())
            clone.updated_at = _now()
            self._sessions[clone.session_id] = clone
            return SessionState.from_dict(clone.to_dict())

    async def delete_session(self, session_id: str) -> bool:
        """Delete one session row.

        Example:
            >>> # await InMemorySessionStore().delete_session("s")
            >>> True
            True
        """

        with self._lock:
            removed = self._sessions.pop(session_id, None) is not None
            self._messages.pop(session_id, None)
            return removed

    async def append_message(self, session_id: str, message: Message) -> Message:
        """Append one message and enforce history cap.

        Example:
            >>> # await InMemorySessionStore().append_message("s", Message("s","user","x"))
            >>> True
            True
        """

        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session '{session_id}' not found.")
            clone = Message.from_dict(message.to_dict())
            clone.session_id = session_id
            rows = self._messages.setdefault(session_id, [])
            rows.append(clone)
            if len(rows) > self.max_history_messages:
                overflow = len(rows) - self.max_history_messages
                del rows[:overflow]
            self._sessions[session_id].updated_at = _now()
            return Message.from_dict(clone.to_dict())

    async def get_messages(self, session_id: str, *, last_n: int | None = None) -> list[Message]:
        """Read ordered messages for one session.

        Example:
            >>> # await InMemorySessionStore().get_messages("s", last_n=5)
            >>> True
            True
        """

        with self._lock:
            rows = list(self._messages.get(session_id, []))
            if last_n is not None and last_n > 0:
                rows = rows[-last_n:]
            return [Message.from_dict(row.to_dict()) for row in rows]

    async def clear_messages(self, session_id: str) -> int:
        """Delete all messages for one session.

        Example:
            >>> # await InMemorySessionStore().clear_messages("s")
            >>> True
            True
        """

        with self._lock:
            rows = self._messages.get(session_id, [])
            cleared = len(rows)
            self._messages[session_id] = []
            if session_id in self._sessions:
                self._sessions[session_id].updated_at = _now()
            return cleared


class SQLiteSessionStore(AbstractSessionStore):
    """SQLite-backed webchat store with WAL and cascade deletes."""

    def __init__(
        self,
        path: str | Path = DEFAULT_SQLITE_PATH,
        *,
        max_history_messages: int = MAX_HISTORY_MESSAGES,
    ) -> None:
        """Initialize SQLite store.

        Example:
            >>> store = SQLiteSessionStore(':memory:')
            >>> isinstance(store, SQLiteSessionStore)
            True
        """

        if max_history_messages <= 0:
            raise ValueError("max_history_messages must be > 0.")
        self.path = Path(path)
        self.max_history_messages = max_history_messages
        self._init_db()

    async def create_session(self, session: SessionState) -> SessionState:
        """Create one session row.

        Example:
            >>> # await SQLiteSessionStore('x.db').create_session(SessionState("s","t","free"))
            >>> True
            True
        """

        return await asyncio.to_thread(self._create_session_sync, session)

    async def get_session(self, session_id: str) -> SessionState | None:
        """Load session by id.

        Example:
            >>> # await SQLiteSessionStore('x.db').get_session("s")
            >>> True
            True
        """

        return await asyncio.to_thread(self._get_session_sync, session_id)

    async def update_session(self, session: SessionState) -> SessionState:
        """Update one existing session row.

        Example:
            >>> # await SQLiteSessionStore('x.db').update_session(SessionState("s","t","free"))
            >>> True
            True
        """

        return await asyncio.to_thread(self._update_session_sync, session)

    async def delete_session(self, session_id: str) -> bool:
        """Delete one session row.

        Example:
            >>> # await SQLiteSessionStore('x.db').delete_session("s")
            >>> True
            True
        """

        return await asyncio.to_thread(self._delete_session_sync, session_id)

    async def append_message(self, session_id: str, message: Message) -> Message:
        """Append one message and enforce history cap.

        Example:
            >>> # await SQLiteSessionStore('x.db').append_message("s", Message("s","user","x"))
            >>> True
            True
        """

        return await asyncio.to_thread(self._append_message_sync, session_id, message)

    async def get_messages(self, session_id: str, *, last_n: int | None = None) -> list[Message]:
        """Read ordered messages for one session.

        Example:
            >>> # await SQLiteSessionStore('x.db').get_messages("s", last_n=5)
            >>> True
            True
        """

        return await asyncio.to_thread(self._get_messages_sync, session_id, last_n)

    async def clear_messages(self, session_id: str) -> int:
        """Delete all messages for one session.

        Example:
            >>> # await SQLiteSessionStore('x.db').clear_messages("s")
            >>> True
            True
        """

        return await asyncio.to_thread(self._clear_messages_sync, session_id)

    async def prune_stale_sessions(self, *, max_age_seconds: int) -> int:
        """Delete stale sessions by `updated_at` age threshold.

        Example:
            >>> # await SQLiteSessionStore('x.db').prune_stale_sessions(max_age_seconds=3600)
            >>> True
            True
        """

        return await asyncio.to_thread(self._prune_stale_sessions_sync, max_age_seconds)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at)"
            )

    def _create_session_sync(self, session: SessionState) -> SessionState:
        now = _now()
        row = SessionState.from_dict(session.to_dict())
        row.updated_at = now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(session_id, tenant_id, tier, metadata, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    tier=excluded.tier,
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """,
                (
                    row.session_id,
                    row.tenant_id,
                    row.tier,
                    json.dumps(row.metadata),
                    row.created_at,
                    row.updated_at,
                ),
            )
        return row

    def _get_session_sync(self, session_id: str) -> SessionState | None:
        with self._connect() as conn:
            record = conn.execute(
                """
                SELECT session_id, tenant_id, tier, metadata, created_at, updated_at
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if record is None:
            return None
        return SessionState(
            session_id=str(record["session_id"]),
            tenant_id=str(record["tenant_id"]),
            tier=str(record["tier"]),
            metadata=json.loads(str(record["metadata"])) if record["metadata"] else {},
            created_at=float(record["created_at"]),
            updated_at=float(record["updated_at"]),
        )

    def _update_session_sync(self, session: SessionState) -> SessionState:
        row = SessionState.from_dict(session.to_dict())
        row.updated_at = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE sessions
                SET tenant_id = ?, tier = ?, metadata = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    row.tenant_id,
                    row.tier,
                    json.dumps(row.metadata),
                    row.updated_at,
                    row.session_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Session '{row.session_id}' not found.")
        return row

    def _delete_session_sync(self, session_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        return cursor.rowcount > 0

    def _append_message_sync(self, session_id: str, message: Message) -> Message:
        row = Message.from_dict(message.to_dict())
        row.session_id = session_id
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(f"Session '{session_id}' not found.")
            conn.execute(
                """
                INSERT INTO messages(id, session_id, role, content, metadata, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    row.id,
                    row.session_id,
                    row.role,
                    row.content,
                    json.dumps(row.metadata),
                    row.created_at,
                ),
            )
            total = conn.execute(
                "SELECT COUNT(*) AS count FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            count = int(total["count"]) if total else 0
            if count > self.max_history_messages:
                overflow = count - self.max_history_messages
                conn.execute(
                    """
                    DELETE FROM messages
                    WHERE id IN (
                        SELECT id FROM messages
                        WHERE session_id = ?
                        ORDER BY created_at ASC, id ASC
                        LIMIT ?
                    )
                    """,
                    (session_id, overflow),
                )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (_now(), session_id),
            )
        return row

    def _get_messages_sync(self, session_id: str, last_n: int | None) -> list[Message]:
        with self._connect() as conn:
            if last_n is not None and last_n > 0:
                records = conn.execute(
                    """
                    SELECT id, session_id, role, content, metadata, created_at
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (session_id, last_n),
                ).fetchall()
                records = list(reversed(records))
            else:
                records = conn.execute(
                    """
                    SELECT id, session_id, role, content, metadata, created_at
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (session_id,),
                ).fetchall()
        return [
            Message(
                id=str(record["id"]),
                session_id=str(record["session_id"]),
                role=str(record["role"]),
                content=str(record["content"]),
                metadata=json.loads(str(record["metadata"])) if record["metadata"] else {},
                created_at=float(record["created_at"]),
            )
            for record in records
        ]

    def _clear_messages_sync(self, session_id: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            if cursor.rowcount > 0:
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                    (_now(), session_id),
                )
        return cursor.rowcount

    def _prune_stale_sessions_sync(self, max_age_seconds: int) -> int:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be > 0.")
        cutoff = _now() - float(max_age_seconds)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM sessions WHERE updated_at < ?",
                (cutoff,),
            )
        return cursor.rowcount


def create_session_store(
    backend: str,
    *,
    sqlite_path: str | Path = DEFAULT_SQLITE_PATH,
    max_history_messages: int = MAX_HISTORY_MESSAGES,
) -> AbstractSessionStore:
    """Build a session store by backend key.

    Example:
        >>> isinstance(create_session_store("memory"), InMemorySessionStore)
        True
    """

    normalized = backend.strip().lower()
    if normalized == "sqlite":
        return SQLiteSessionStore(
            path=sqlite_path,
            max_history_messages=max_history_messages,
        )
    if normalized == "memory":
        return InMemorySessionStore(max_history_messages=max_history_messages)
    if normalized == "redis":
        raise NotImplementedError("Redis session store is not implemented.")
    raise ValueError(f"Unsupported session store backend '{backend}'.")
