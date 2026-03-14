"""Local Ollama embedder with SQLite hash cache and graceful fallback."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from contextlib import closing
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


class Embedder:
    """Embeddings provider that always uses local Ollama nomic-embed-text."""

    def __init__(
        self,
        *,
        db_path: str = "archon_memory.sqlite3",
        model: str = "nomic-embed-text",
        default_dim: int = 768,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.db_path = db_path
        self.model = model
        self.default_dim = max(1, int(default_dim))
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self._client = httpx.Client(timeout=timeout_seconds)
        self._ensure_cache_schema()

    def close(self) -> None:
        """Close http resources."""

        self._client.close()

    def embed(self, text: str) -> list[float]:
        """Embed one string. Returns zero-vector on Ollama failure."""

        normalized = str(text)
        cached = self._load_cache(normalized)
        if cached is not None:
            return cached

        response = self._embed_remote([normalized])
        vector = response[0] if response else self._zero_vector()
        self._store_cache(normalized, vector)
        return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed batch with cache dedupe and one HTTP call for all misses."""

        if not texts:
            return []

        outputs: list[list[float] | None] = [None for _ in texts]
        missing_texts: list[str] = []
        missing_indices_by_text: dict[str, list[int]] = {}
        for idx, text in enumerate(texts):
            normalized = str(text)
            cached = self._load_cache(normalized)
            if cached is not None:
                outputs[idx] = cached
                continue
            if normalized not in missing_indices_by_text:
                missing_texts.append(normalized)
                missing_indices_by_text[normalized] = []
            missing_indices_by_text[normalized].append(idx)

        if missing_texts:
            vectors = self._embed_remote(missing_texts)
            if len(vectors) != len(missing_texts):
                vectors = [self._zero_vector() for _ in missing_texts]
            for text, vector in zip(missing_texts, vectors):
                self._store_cache(text, vector)
                for idx in missing_indices_by_text[text]:
                    outputs[idx] = vector

        return [vector if vector is not None else self._zero_vector() for vector in outputs]

    def _embed_remote(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            if len(texts) == 1:
                payload = {"model": self.model, "prompt": texts[0]}
                response = self._client.post(f"{self.base_url}/api/embeddings", json=payload)
                response.raise_for_status()
                data = response.json()
                vector = _coerce_vector(data.get("embedding"))
                return [vector if vector else self._zero_vector()]

            payload = {"model": self.model, "input": texts}
            response = self._client.post(f"{self.base_url}/api/embed", json=payload)
            response.raise_for_status()
            data = response.json()
            batch = data.get("embeddings")
            if isinstance(batch, list) and batch:
                return [(_coerce_vector(item) or self._zero_vector()) for item in batch]
            return [self._zero_vector() for _ in texts]
        except Exception as exc:
            LOGGER.warning("Ollama embedding unavailable; using zero-vector fallback: %s", exc)
            return [self._zero_vector() for _ in texts]

    def _ensure_cache_schema(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    text_hash TEXT PRIMARY KEY,
                    vector_json TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def _load_cache(self, text: str) -> list[float] | None:
        text_hash = _hash_text(text)
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT vector_json FROM embedding_cache WHERE text_hash = ?",
                (text_hash,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row[0]))
            vector = _coerce_vector(payload)
            return vector if vector else self._zero_vector()
        except json.JSONDecodeError:
            return None

    def _store_cache(self, text: str, vector: list[float]) -> None:
        text_hash = _hash_text(text)
        vector_json = json.dumps(vector, separators=(",", ":"))
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO embedding_cache (text_hash, vector_json)
                VALUES (?, ?)
                ON CONFLICT(text_hash) DO UPDATE SET vector_json = excluded.vector_json
                """,
                (text_hash, vector_json),
            )
            conn.commit()

    def _zero_vector(self) -> list[float]:
        return [0.0 for _ in range(self.default_dim)]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _coerce_vector(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    output: list[float] = []
    for item in value:
        try:
            output.append(float(item))
        except (TypeError, ValueError):
            return []
    return output
