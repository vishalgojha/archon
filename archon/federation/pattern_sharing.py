"""Differentially-private workflow pattern sharing for federation."""

from __future__ import annotations

import asyncio
import math
import os
import random
from dataclasses import dataclass, replace
from typing import Any

import httpx

from archon.federation.auth import json_bytes, path_with_query, signed_headers


@dataclass(slots=True, frozen=True)
class WorkflowPattern:
    """Serializable workflow pattern summary."""

    pattern_id: str
    workflow_type: str
    step_sequence: list[str]
    avg_score: float
    sample_count: int


class PatternStore:
    """In-memory pattern store with merge semantics for shared IDs."""

    def __init__(self, *, store: Any | None = None) -> None:
        self.patterns: dict[str, WorkflowPattern] = {}
        self._store = store
        if self._store is not None:
            try:
                for pattern in list(self._store.list_patterns(limit=500)):
                    self.patterns[pattern.pattern_id] = pattern
            except Exception:
                self.patterns = {}

    def merge(self, incoming: WorkflowPattern) -> WorkflowPattern:
        """Merge incoming pattern, averaging score for known IDs."""

        existing = self.patterns.get(incoming.pattern_id)
        if existing is None:
            self.patterns[incoming.pattern_id] = incoming
            if self._store is not None:
                try:
                    self._store.upsert_pattern(incoming)
                except Exception:
                    pass
            return incoming

        merged = WorkflowPattern(
            pattern_id=existing.pattern_id,
            workflow_type=incoming.workflow_type or existing.workflow_type,
            step_sequence=incoming.step_sequence or existing.step_sequence,
            avg_score=(existing.avg_score + incoming.avg_score) / 2.0,
            sample_count=max(1, int(round((existing.sample_count + incoming.sample_count) / 2.0))),
        )
        self.patterns[incoming.pattern_id] = merged
        if self._store is not None:
            try:
                self._store.upsert_pattern(merged)
            except Exception:
                pass
        return merged

    def get(self, pattern_id: str) -> WorkflowPattern | None:
        """Lookup one pattern by ID."""

        return self.patterns.get(pattern_id)


class PatternSharer:
    """Shares workflow patterns with epsilon-DP privatization."""

    def __init__(
        self,
        *,
        pattern_store: PatternStore | None = None,
        min_score: float = 0.0,
        max_score: float = 1.0,
        timeout_seconds: float = 5.0,
        rng: random.Random | None = None,
    ) -> None:
        self.pattern_store = pattern_store or PatternStore()
        self.min_score = float(min_score)
        self.max_score = float(max_score)
        self._client = httpx.AsyncClient(timeout=timeout_seconds)
        self._rng = rng or random.Random()

    async def aclose(self) -> None:
        """Close outbound HTTP resources."""

        await self._client.aclose()

    def privatize(self, pattern: WorkflowPattern, epsilon: float = 1.0) -> WorkflowPattern:
        """Apply calibrated Laplace noise to numeric fields."""

        epsilon = max(float(epsilon), 1e-6)
        sensitivity = self.max_score - self.min_score
        scale = sensitivity / epsilon
        noisy_avg = _clip(
            pattern.avg_score + _laplace(self._rng, scale), self.min_score, self.max_score
        )
        noisy_count = max(1, int(round(pattern.sample_count + _laplace(self._rng, scale))))
        return replace(pattern, avg_score=noisy_avg, sample_count=noisy_count)

    async def share(self, pattern: WorkflowPattern, peers: list[Any], epsilon: float = 1.0) -> int:
        """POST privatized pattern to each peer's `/federation/patterns` endpoint."""

        privatized = self.privatize(pattern, epsilon=epsilon)
        payload = _pattern_to_dict(privatized)
        tasks = []
        for peer in peers:
            address = _extract_peer_address(peer)
            if not address:
                continue
            url = f"{address.rstrip('/')}/federation/patterns"
            tasks.append(asyncio.create_task(self._post(url, payload)))
        if not tasks:
            return 0
        results = await asyncio.gather(*tasks)
        return sum(1 for row in results if row)

    async def receive(self, raw_pattern: dict[str, Any]) -> WorkflowPattern:
        """Validate incoming pattern, clip extremes, and store locally."""

        validated = _validate_pattern_payload(raw_pattern)
        clipped = WorkflowPattern(
            pattern_id=validated.pattern_id,
            workflow_type=validated.workflow_type,
            step_sequence=validated.step_sequence,
            avg_score=_clip(validated.avg_score, self.min_score, self.max_score),
            sample_count=min(max(1, int(validated.sample_count)), 1_000_000),
        )
        return self.pattern_store.merge(clipped)

    async def _post(self, url: str, payload: dict[str, Any]) -> bool:
        try:
            secret = str(os.getenv("ARCHON_FEDERATION_SHARED_SECRET", "")).strip()
            if secret:
                body = json_bytes(payload)
                actor = (
                    str(os.getenv("ARCHON_INSTANCE_ID", "local-instance")).strip()
                    or "local-instance"
                )
                headers = signed_headers(
                    secret=secret,
                    method="POST",
                    path=path_with_query(url),
                    body=body,
                    peer_id=actor,
                )
                headers["Content-Type"] = "application/json"
                response = await self._client.post(url, content=body, headers=headers)
            else:
                response = await self._client.post(url, json=payload)
            return response.status_code < 400
        except Exception:
            return False


def _laplace(rng: random.Random, scale: float) -> float:
    if scale <= 0:
        return 0.0
    u = rng.random() - 0.5
    return -scale * math.copysign(math.log(1.0 - 2.0 * abs(u)), u)


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _validate_pattern_payload(raw_pattern: dict[str, Any]) -> WorkflowPattern:
    required = {"pattern_id", "workflow_type", "step_sequence", "avg_score", "sample_count"}
    if not isinstance(raw_pattern, dict):
        raise ValueError("Pattern payload must be a JSON object.")
    missing = required - set(raw_pattern.keys())
    if missing:
        raise ValueError(f"Pattern payload missing required keys: {sorted(missing)}")
    step_sequence = raw_pattern["step_sequence"]
    if not isinstance(step_sequence, list):
        raise ValueError("step_sequence must be a list.")
    return WorkflowPattern(
        pattern_id=str(raw_pattern["pattern_id"]),
        workflow_type=str(raw_pattern["workflow_type"]),
        step_sequence=[str(item) for item in step_sequence],
        avg_score=float(raw_pattern["avg_score"]),
        sample_count=int(raw_pattern["sample_count"]),
    )


def _pattern_to_dict(pattern: WorkflowPattern) -> dict[str, Any]:
    return {
        "pattern_id": pattern.pattern_id,
        "workflow_type": pattern.workflow_type,
        "step_sequence": pattern.step_sequence,
        "avg_score": pattern.avg_score,
        "sample_count": pattern.sample_count,
    }


def _extract_peer_address(peer: Any) -> str | None:
    if isinstance(peer, str):
        return peer
    address = getattr(peer, "address", None)
    if isinstance(address, str):
        return address
    if isinstance(peer, dict) and isinstance(peer.get("address"), str):
        return peer["address"]
    return None
