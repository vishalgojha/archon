"""Training dataset builder from episodic memory and causal chains."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from archon.memory.store import MemoryStore

if TYPE_CHECKING:
    from archon.finetune.quality_scorer import QualityScorer


@dataclass(slots=True)
class TrainingExample:
    """Fine-tuning-ready training pair with provenance metadata."""

    example_id: str
    prompt: str
    completion: str
    quality_score: float
    source_memory_ids: list[str] = field(default_factory=list)
    source_chains: list[str] = field(default_factory=list)


class DatasetBuilder:
    """Build fine-tuning datasets from memory and causal chain records."""

    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        quality_scorer: QualityScorer | None = None,
        icp_keywords: Sequence[str] | None = None,
    ) -> None:
        self.memory_store = memory_store or MemoryStore()
        self._owns_memory_store = memory_store is None
        if quality_scorer is None:
            from archon.finetune.quality_scorer import QualityScorer as _QualityScorer

            quality_scorer = _QualityScorer()
        self.quality_scorer = quality_scorer
        self.icp_keywords = [
            str(item).strip().lower() for item in (icp_keywords or ()) if str(item).strip()
        ]

    def close(self) -> None:
        """Close resources owned by this builder."""

        if self._owns_memory_store:
            self.memory_store.close()

    def build_from_memories(
        self, tenant_id: str, min_quality: float = 0.7
    ) -> list[TrainingExample]:
        """Create user->assistant training examples from episodic memory pairs."""

        threshold = self._clamp(min_quality)
        tenant = str(tenant_id or "").strip()
        if not tenant:
            raise ValueError("tenant_id is required.")

        with sqlite3.connect(self.memory_store.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT memory_id, content, role, session_id, timestamp
                FROM episodic_memory
                WHERE tenant_id = ? AND forgotten = 0
                ORDER BY session_id ASC, timestamp ASC
                """,
                (tenant,),
            ).fetchall()

        pending_user: dict[str, tuple[str, str]] = {}
        examples: list[TrainingExample] = []
        for row in rows:
            role = str(row["role"]).strip().lower()
            session_id = str(row["session_id"])
            memory_id = str(row["memory_id"])
            content = str(row["content"])

            if role == "user":
                pending_user[session_id] = (memory_id, content)
                continue

            if role != "assistant" or session_id not in pending_user:
                continue

            user_memory_id, prompt = pending_user.pop(session_id)
            quality = self._score_memory_example(prompt=prompt, completion=content)
            if quality < threshold:
                continue

            examples.append(
                TrainingExample(
                    example_id=f"ft-mem-{uuid.uuid4().hex[:12]}",
                    prompt=prompt,
                    completion=content,
                    quality_score=quality,
                    source_memory_ids=[user_memory_id, memory_id],
                    source_chains=[],
                )
            )
        return examples

    def build_from_causal_chains(self, tenant_id: str) -> list[TrainingExample]:
        """Create reasoning examples from causal chain links."""

        tenant = str(tenant_id or "").strip()
        if not tenant:
            raise ValueError("tenant_id is required.")

        with sqlite3.connect(self.memory_store.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT chain_id, event, cause, effect, confidence, supporting_memory_ids_json
                FROM causal_chains
                WHERE tenant_id = ?
                ORDER BY timestamp ASC
                """,
                (tenant,),
            ).fetchall()

        output: list[TrainingExample] = []
        for row in rows:
            chain_id = str(row["chain_id"])
            cause = str(row["cause"])
            event = str(row["event"])
            effect = str(row["effect"])
            confidence = self._clamp(float(row["confidence"]))
            supporting_ids = _safe_json_list(str(row["supporting_memory_ids_json"]))

            prompt = f"Situation: {cause}"
            completion = (
                "Reasoning steps:\n"
                f"1. Observed event: {event}\n"
                f"2. Identify root cause: {cause}\n"
                f"3. Trace downstream effect: {effect}\n"
                f"4. Confidence: {confidence:.2f}\n"
                f"Conclusion: {effect} is a likely consequence of {cause}."
            )

            output.append(
                TrainingExample(
                    example_id=f"ft-chain-{uuid.uuid4().hex[:12]}",
                    prompt=prompt,
                    completion=completion,
                    quality_score=round((confidence + self._length_score(completion)) / 2.0, 4),
                    source_memory_ids=[str(item) for item in supporting_ids],
                    source_chains=[chain_id],
                )
            )
        return output

    def deduplicate(self, examples: Iterable[TrainingExample]) -> list[TrainingExample]:
        """Drop near-duplicate examples by Jaccard similarity (> 0.85)."""

        kept: list[TrainingExample] = []
        token_sets: list[set[str]] = []

        for example in examples:
            tokens = _tokenize(f"{example.prompt}\n{example.completion}")
            duplicate = False
            for existing_tokens in token_sets:
                similarity = _jaccard_similarity(tokens, existing_tokens)
                if similarity > 0.85:
                    duplicate = True
                    break
            if duplicate:
                continue
            kept.append(example)
            token_sets.append(tokens)

        return kept

    def export_jsonl(self, examples: Iterable[TrainingExample], path: str | Path) -> None:
        """Export examples in OpenAI fine-tune chat JSONL format."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for example in examples:
                row = {
                    "messages": [
                        {"role": "user", "content": example.prompt},
                        {"role": "assistant", "content": example.completion},
                    ]
                }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def export_alpaca(self, examples: Iterable[TrainingExample], path: str | Path) -> None:
        """Export examples in Alpaca instruction JSONL format."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for example in examples:
                row = {
                    "instruction": example.prompt,
                    "input": "",
                    "output": example.completion,
                }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _score_memory_example(self, *, prompt: str, completion: str) -> float:
        length_score = self._length_score(completion)
        coherence_score = self._coherence_score(prompt, completion)
        relevance_score = self._relevance_score(prompt, completion)
        return round((length_score + coherence_score + relevance_score) / 3.0, 4)

    def _length_score(self, completion: str) -> float:
        scorer = self.quality_scorer
        length_fn = getattr(scorer, "length_score", None)
        if callable(length_fn):
            return self._clamp(float(length_fn(completion)))
        return 1.0 if len(completion) >= 500 else max(0.0, (len(completion) - 50.0) / 450.0)

    def _coherence_score(self, prompt: str, completion: str) -> float:
        scorer = self.quality_scorer
        judge_fn = getattr(scorer, "judge_coherence", None)
        if callable(judge_fn):
            return self._clamp(float(judge_fn(prompt, completion)))
        score_fn = getattr(scorer, "score", None)
        if callable(score_fn):
            estimate = score_fn(
                TrainingExample(
                    example_id="tmp",
                    prompt=prompt,
                    completion=completion,
                    quality_score=0.0,
                    source_memory_ids=[],
                    source_chains=[],
                )
            )
            return self._clamp(float(estimate))
        return 0.5

    def _relevance_score(self, prompt: str, completion: str) -> float:
        if not self.icp_keywords:
            return 0.5
        text = f"{prompt}\n{completion}".lower()
        hits = sum(1 for keyword in self.icp_keywords if keyword in text)
        return self._clamp(hits / float(len(self.icp_keywords)))

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))


def _safe_json_list(payload: str) -> list[Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(text).lower()))


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / float(len(union))
