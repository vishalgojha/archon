"""Tests for webchat auth and session storage backends."""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

import pytest

from archon.interfaces.webchat.auth import (
    ANON_TOKEN_TTL_SECONDS,
    WebChatTokenError,
    create_anonymous_token,
    create_identified_token,
    identity_to_tenant_context,
    verify_webchat_token,
)
from archon.interfaces.webchat.session_store import (
    MAX_HISTORY_MESSAGES,
    InMemorySessionStore,
    Message,
    SessionState,
    SQLiteSessionStore,
    create_session_store,
)


def _temp_db_path(prefix: str) -> Path:
    base = Path("archon/tests/_tmp_webchat")
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{prefix}-{uuid.uuid4().hex[:8]}.sqlite3"


def test_webchat_identity_creation_and_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "webchat-test-secret-0123456789abcdef")
    anon = create_anonymous_token("session-a")
    identified = create_identified_token("tenant-1", "growth", "session-a")

    assert anon.is_anonymous is True
    assert anon.tenant_id.startswith("anon:")
    assert len(anon.tenant_id.split(":", 1)[1]) == 12
    assert anon.expires_at - anon.issued_at == ANON_TOKEN_TTL_SECONDS

    verified_anon = verify_webchat_token(anon.token)
    verified_identified = verify_webchat_token(identified.token)
    assert verified_anon.session_id == "session-a"
    assert verified_identified.tenant_id == "tenant-1"
    assert verified_identified.tier == "growth"

    context = identity_to_tenant_context(verified_identified)
    assert context.tenant_id == "tenant-1"
    assert context.tier == "pro"


def test_webchat_token_tamper_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "webchat-test-secret-0123456789abcdef")
    identity = create_identified_token("tenant-1", "pro", "session-a")
    parts = identity.token.split(".")
    assert len(parts) == 3
    tampered_signature = ("a" if parts[2][0] != "a" else "b") + parts[2][1:]
    tampered = ".".join([parts[0], parts[1], tampered_signature])

    with pytest.raises(WebChatTokenError):
        verify_webchat_token(tampered)


def test_webchat_token_expiry_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "webchat-test-secret-0123456789abcdef")
    expired = create_identified_token("tenant-1", "pro", "session-a", now=1, expires_in_seconds=1)

    with pytest.raises(WebChatTokenError):
        verify_webchat_token(expired.token)


def test_message_model_auto_id_and_roundtrip() -> None:
    message = Message(session_id="session-1", role="user", content="hello")
    payload = message.to_dict()
    restored = Message.from_dict(payload)

    assert message.id.startswith("msg-")
    assert len(message.id) == len("msg-") + 12
    assert restored.to_dict() == payload


@pytest.mark.asyncio
async def test_in_memory_session_store_crud_ordering_cap_and_isolation() -> None:
    store = InMemorySessionStore(max_history_messages=3)
    await store.create_session(SessionState(session_id="s1", tenant_id="tenant-1", tier="free"))
    await store.create_session(SessionState(session_id="s2", tenant_id="tenant-2", tier="free"))

    session = await store.get_session("s1")
    assert session is not None
    session.metadata["channel"] = "webchat"
    await store.update_session(session)

    for index in range(4):
        await store.append_message(
            "s1",
            Message(
                session_id="s1",
                role="user" if index % 2 == 0 else "assistant",
                content=f"message-{index}",
                created_at=float(index + 1),
            ),
        )
    await store.append_message("s2", Message(session_id="s2", role="user", content="other-session"))

    all_messages = await store.get_messages("s1")
    last_two = await store.get_messages("s1", last_n=2)
    isolated = await store.get_messages("s2")

    assert [row.content for row in all_messages] == ["message-1", "message-2", "message-3"]
    assert [row.content for row in last_two] == ["message-2", "message-3"]
    assert [row.content for row in isolated] == ["other-session"]

    cleared = await store.clear_messages("s1")
    assert cleared == 3
    assert await store.get_messages("s1") == []
    assert await store.delete_session("s1") is True
    assert await store.get_session("s1") is None


@pytest.mark.asyncio
async def test_sqlite_session_store_persistence_across_reopen_and_cascade_delete() -> None:
    db_path = _temp_db_path("webchat")
    first = SQLiteSessionStore(path=db_path, max_history_messages=MAX_HISTORY_MESSAGES)
    await first.create_session(SessionState(session_id="s1", tenant_id="tenant-1", tier="free"))
    await first.append_message("s1", Message(session_id="s1", role="user", content="persist-me"))

    reopened = SQLiteSessionStore(path=db_path, max_history_messages=MAX_HISTORY_MESSAGES)
    loaded = await reopened.get_session("s1")
    messages_before_delete = await reopened.get_messages("s1")

    assert loaded is not None
    assert loaded.tenant_id == "tenant-1"
    assert [row.content for row in messages_before_delete] == ["persist-me"]

    assert await reopened.delete_session("s1") is True
    assert await reopened.get_session("s1") is None
    assert await reopened.get_messages("s1") == []


@pytest.mark.asyncio
async def test_sqlite_session_store_prune_stale_sessions() -> None:
    db_path = _temp_db_path("webchat-prune")
    store = SQLiteSessionStore(path=db_path, max_history_messages=MAX_HISTORY_MESSAGES)
    await store.create_session(SessionState(session_id="fresh", tenant_id="t1", tier="free"))
    await store.create_session(SessionState(session_id="stale", tenant_id="t2", tier="free"))
    await store.append_message(
        "stale", Message(session_id="stale", role="user", content="old-message")
    )

    stale_updated_at = time.time() - 10_000
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (stale_updated_at, "stale"),
        )

    pruned = await store.prune_stale_sessions(max_age_seconds=3600)
    stale_session = await store.get_session("stale")
    stale_messages = await store.get_messages("stale")
    fresh_session = await store.get_session("fresh")

    assert pruned == 1
    assert stale_session is None
    assert stale_messages == []
    assert fresh_session is not None


def test_create_session_store_factory() -> None:
    memory = create_session_store("memory")
    sqlite = create_session_store("sqlite", sqlite_path=_temp_db_path("factory"))

    assert isinstance(memory, InMemorySessionStore)
    assert isinstance(sqlite, SQLiteSessionStore)
    with pytest.raises(NotImplementedError):
        create_session_store("redis")
