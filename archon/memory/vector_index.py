"""In-process vector search with optional ChromaDB backend delegation."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class SearchResult:
    """Vector search result row."""

    id: str
    similarity: float
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorIndex:
    """Vector index that defaults to pure-python cosine similarity search."""

    def __init__(
        self, *, backend: str | None = None, collection_name: str = "archon_memory"
    ) -> None:
        selected = (backend or os.getenv("ARCHON_VECTOR_BACKEND", "python")).strip().lower()
        self._backend = "python"
        self._vectors: dict[str, tuple[list[float], dict[str, Any]]] = {}
        self._collection = None
        if selected == "chromadb":
            try:
                import chromadb  # type: ignore[import-not-found]

                client = chromadb.Client()
                self._collection = client.get_or_create_collection(name=collection_name)
                self._backend = "chromadb"
            except Exception:
                self._backend = "python"

    @property
    def count(self) -> int:
        """Return number of indexed vectors."""

        if self._backend == "chromadb" and self._collection is not None:
            return int(self._collection.count())
        return len(self._vectors)

    def add(self, id: str, vector: list[float], metadata: dict[str, Any]) -> None:
        """Add or replace one vector entry."""

        if self._backend == "chromadb" and self._collection is not None:
            self._collection.upsert(ids=[id], embeddings=[vector], metadatas=[dict(metadata)])
            return
        self._vectors[id] = (list(vector), dict(metadata))

    def search(
        self, query_vector: list[float], top_k: int, min_similarity: float
    ) -> list[SearchResult]:
        """Search most-similar vectors for query."""

        top_k = max(1, int(top_k))
        min_similarity = float(min_similarity)
        if self._backend == "chromadb" and self._collection is not None:
            if self.count == 0:
                return []
            results = self._collection.query(
                query_embeddings=[query_vector],
                n_results=top_k,
                include=["metadatas", "distances"],
            )
            ids = (results.get("ids") or [[]])[0]
            metadatas = (results.get("metadatas") or [[]])[0]
            distances = (results.get("distances") or [[]])[0]
            output: list[SearchResult] = []
            for idx, item_id in enumerate(ids):
                distance = float(distances[idx]) if idx < len(distances) else 2.0
                similarity = max(0.0, 1.0 - distance)
                if similarity >= min_similarity:
                    metadata = (
                        metadatas[idx]
                        if idx < len(metadatas) and isinstance(metadatas[idx], dict)
                        else {}
                    )
                    output.append(
                        SearchResult(
                            id=str(item_id),
                            similarity=round(similarity, 6),
                            metadata=dict(metadata),
                        )
                    )
            return output

        scored: list[SearchResult] = []
        for item_id, (vector, metadata) in self._vectors.items():
            similarity = cosine_similarity(query_vector, vector)
            if similarity >= min_similarity:
                scored.append(
                    SearchResult(
                        id=item_id, similarity=round(similarity, 6), metadata=dict(metadata)
                    )
                )
        scored.sort(key=lambda row: row.similarity, reverse=True)
        return scored[:top_k]

    def delete(self, id: str) -> None:
        """Remove one vector from index."""

        if self._backend == "chromadb" and self._collection is not None:
            self._collection.delete(ids=[id])
            return
        self._vectors.pop(id, None)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between numeric vectors using stdlib only."""

    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for idx in range(n):
        aval = float(a[idx])
        bval = float(b[idx])
        dot += aval * bval
        norm_a += aval * aval
        norm_b += bval * bval
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
