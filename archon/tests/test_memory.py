"""Tests for memory embedder, vector index, and memory store."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from archon.memory.embedder import Embedder
from archon.memory.store import MemoryStore
from archon.memory.vector_index import VectorIndex, cosine_similarity


def _tmp_dir(name: str) -> Path:
    path = Path("archon/tests") / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeClient:
    calls: list[tuple[str, dict[str, object]]] = []
    fail = False

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        del args, kwargs

    def close(self) -> None:
        return None

    def post(self, url: str, json: dict[str, object]):  # type: ignore[no-untyped-def]
        self.__class__.calls.append((url, json))
        if self.__class__.fail:
            raise RuntimeError("ollama unavailable")
        if url.endswith("/api/embeddings"):
            return _FakeResponse({"embedding": [0.1, 0.2, 0.3]})
        return _FakeResponse({"embeddings": [[0.1, 0.2, 0.3] for _ in json.get("input", [])]})


def test_embedder_embed_and_batch_cache_and_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.memory.embedder as embedder_module

    tmp = _tmp_dir("_tmp_embedder")
    db_path = str(tmp / "memory.sqlite3")
    _FakeClient.calls = []
    _FakeClient.fail = False
    monkeypatch.setattr(embedder_module.httpx, "Client", _FakeClient)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://local-ollama:11434")

    embedder = Embedder(db_path=db_path, default_dim=3)
    v1 = embedder.embed("hello")
    assert v1 == [0.1, 0.2, 0.3]
    assert len(_FakeClient.calls) == 1

    v2 = embedder.embed("hello")
    assert v2 == v1
    assert len(_FakeClient.calls) == 1  # cache hit, no extra HTTP

    batch = embedder.embed_batch(["a", "b", "a"])
    assert batch[0] == [0.1, 0.2, 0.3]
    assert batch[1] == [0.1, 0.2, 0.3]
    assert batch[2] == [0.1, 0.2, 0.3]
    batch_calls = [row for row in _FakeClient.calls if row[0].endswith("/api/embed")]
    assert len(batch_calls) == 1
    assert batch_calls[0][1]["input"] == ["a", "b"]  # only unique misses

    _FakeClient.fail = True
    fallback = embedder.embed("unreachable-case")
    assert fallback == [0.0, 0.0, 0.0]
    embedder.close()


def test_vector_index_pure_python_search_min_similarity_delete() -> None:
    index = VectorIndex(backend="python")
    index.add("a", [1.0, 0.0], {"tenant": "t1"})
    index.add("b", [0.0, 1.0], {"tenant": "t1"})
    index.add("c", [0.7, 0.7], {"tenant": "t1"})
    assert index.count == 3

    result = index.search([1.0, 0.0], top_k=2, min_similarity=0.0)
    assert [row.id for row in result] == ["a", "c"]

    filtered = index.search([1.0, 0.0], top_k=5, min_similarity=0.95)
    assert [row.id for row in filtered] == ["a"]

    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0, abs=1e-6)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0, abs=1e-6)
    assert cosine_similarity([1.0, 1.0], [1.0, 1.0]) == pytest.approx(1.0, abs=1e-6)
    assert cosine_similarity([1.0, 2.0], [-1.0, -2.0]) == pytest.approx(-1.0, abs=1e-6)

    index.delete("a")
    assert index.count == 2
    remaining = index.search([1.0, 0.0], top_k=5, min_similarity=-1.0)
    assert all(row.id != "a" for row in remaining)


def test_vector_index_chromadb_backend_if_available(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("chromadb")
    monkeypatch.setenv("ARCHON_VECTOR_BACKEND", "chromadb")
    index = VectorIndex()
    index.add("x", [1.0, 0.0], {"tenant_id": "t1"})
    index.add("y", [0.0, 1.0], {"tenant_id": "t1"})
    result = index.search([1.0, 0.0], top_k=2, min_similarity=0.0)
    assert result
    assert result[0].id in {"x", "y"}


class _DeterministicEmbedder:
    def embed(self, text: str) -> list[float]:
        t = text.lower()
        if "alpha" in t:
            return [1.0, 0.0, 0.0]
        if "beta" in t:
            return [0.0, 1.0, 0.0]
        return [0.3, 0.3, 0.4]

    def close(self) -> None:
        return None


def test_memory_store_add_search_tenant_isolation_causal_and_forget() -> None:
    tmp = _tmp_dir("_tmp_memory_store")
    db_path = str(tmp / "memory.sqlite3")
    store = MemoryStore(
        db_path=db_path,
        embedder=_DeterministicEmbedder(),
        vector_index=VectorIndex(backend="python"),
    )
    try:
        m1 = store.add(
            content="alpha launch docs",
            role="assistant",
            session_id="s-a",
            tenant_id="tenant-a",
            metadata={"topic": "alpha"},
        )
        m2 = store.add(
            content="beta pricing update",
            role="assistant",
            session_id="s-b",
            tenant_id="tenant-b",
            metadata={"topic": "beta"},
        )
        m3 = store.add(
            content="alpha follow-up",
            role="user",
            session_id="s-a",
            tenant_id="tenant-a",
            metadata={"topic": "alpha2"},
        )

        assert m1.memory_id and m1.tenant_id == "tenant-a"
        assert m2.tenant_id == "tenant-b"

        hits_a = store.search("alpha question", tenant_id="tenant-a", top_k=10, min_similarity=0.0)
        assert hits_a
        assert all(row.memory.tenant_id == "tenant-a" for row in hits_a)
        assert all(row.memory.memory_id != m2.memory_id for row in hits_a)

        chain_1 = store.add_causal_link(
            "signup friction", "drop in conversion", 0.92, [m1.memory_id], tenant_id="tenant-a"
        )
        chain_2 = store.add_causal_link(
            "drop in conversion",
            "revenue decline",
            0.88,
            [m1.memory_id, m3.memory_id],
            tenant_id="tenant-a",
        )
        assert chain_1.chain_id and chain_2.chain_id

        traversed = store.get_causal_chain("signup friction", depth=3, tenant_id="tenant-a")
        assert [row.effect for row in traversed] == ["drop in conversion", "revenue decline"]

        context = store.get_session_context("s-a", last_n=10, tenant_id="tenant-a")
        assert [row.session_id for row in context] == ["s-a", "s-a"]

        store.forget(m1.memory_id)
        post_forget = store.search(
            "alpha question", tenant_id="tenant-a", top_k=10, min_similarity=0.0
        )
        assert all(row.memory.memory_id != m1.memory_id for row in post_forget)

        with sqlite3_connect(db_path) as conn:
            row = conn.execute(
                "SELECT forgotten FROM episodic_memory WHERE memory_id = ?",
                (m1.memory_id,),
            ).fetchone()
            assert row is not None
            assert int(row[0]) == 1
    finally:
        store.close()


def sqlite3_connect(path: str):  # type: ignore[no-untyped-def]
    import sqlite3

    return sqlite3.connect(path)
