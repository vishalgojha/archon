"""Quality scoring utilities for fine-tuning training examples."""

from __future__ import annotations

import re
from collections.abc import Callable

from archon.finetune.dataset_builder import TrainingExample


class QualityScorer:
    """Scores examples on length, specificity, coherence, and instruction following."""

    def __init__(
        self,
        coherence_judge: Callable[[str, str], float] | None = None,
        batch_coherence_judge: Callable[[list[TrainingExample]], list[float]] | None = None,
    ) -> None:
        self._coherence_judge = coherence_judge or self._default_coherence_judge
        self._batch_coherence_judge = batch_coherence_judge

    def length_score(self, completion: str) -> float:
        """Length score: 0 below 50 chars, 1 above 500 chars, linear in-between."""

        size = len(str(completion or ""))
        if size < 50:
            return 0.0
        if size > 500:
            return 1.0
        return (size - 50.0) / 450.0

    def specificity_score(self, completion: str) -> float:
        """Approximate named-entity density using capitalized words."""

        words = _words(completion)
        if not words:
            return 0.0
        capitalized = [word for word in words if word[0].isupper()]
        return len(capitalized) / float(len(words))

    def instruction_following_score(self, prompt: str, completion: str) -> float:
        """Keyword overlap score between prompt and completion."""

        prompt_terms = {word for word in _words(prompt) if len(word) >= 4}
        completion_terms = {word for word in _words(completion)}
        if not prompt_terms:
            return 1.0 if str(completion or "").strip() else 0.0
        overlap = prompt_terms & completion_terms
        return len(overlap) / float(len(prompt_terms))

    def judge_coherence(self, prompt: str, completion: str) -> float:
        """Return coherence score on the required 0 / 0.5 / 1.0 scale."""

        raw = float(self._coherence_judge(prompt, completion))
        return _normalize_coherence(raw)

    def score(self, example: TrainingExample) -> float:
        """Return a [0,1] quality score with equal weights per dimension."""

        parts = [
            self.length_score(example.completion),
            self.specificity_score(example.completion),
            self.judge_coherence(example.prompt, example.completion),
            self.instruction_following_score(example.prompt, example.completion),
        ]
        return max(0.0, min(1.0, sum(parts) / float(len(parts))))

    def score_batch(self, examples: list[TrainingExample]) -> list[float]:
        """Batch score examples while batching coherence judgment calls."""

        if not examples:
            return []

        if self._batch_coherence_judge is not None:
            coherence_rows = self._batch_coherence_judge(examples)
        else:
            coherence_rows = [
                self._coherence_judge(item.prompt, item.completion) for item in examples
            ]

        normalized = [_normalize_coherence(float(item)) for item in coherence_rows]
        scores: list[float] = []
        for example, coherence in zip(examples, normalized, strict=False):
            parts = [
                self.length_score(example.completion),
                self.specificity_score(example.completion),
                coherence,
                self.instruction_following_score(example.prompt, example.completion),
            ]
            scores.append(max(0.0, min(1.0, sum(parts) / float(len(parts)))))

        # If a custom batch judge returned fewer rows, pad safely.
        while len(scores) < len(examples):
            scores.append(self.score(examples[len(scores)]))
        return scores[: len(examples)]

    @staticmethod
    def _default_coherence_judge(prompt: str, completion: str) -> float:
        text = str(completion or "").strip()
        if len(text) < 30:
            return 0.0

        prompt_terms = {word for word in _words(prompt) if len(word) >= 4}
        completion_terms = set(_words(text))
        overlap_ratio = 0.0
        if prompt_terms:
            overlap_ratio = len(prompt_terms & completion_terms) / float(len(prompt_terms))

        if len(text) > 120 and overlap_ratio >= 0.2:
            return 1.0
        if len(text) > 60 and overlap_ratio > 0.0:
            return 0.5
        if len(text) > 160:
            return 0.5
        return 0.0


def _normalize_coherence(score: float) -> float:
    if score <= 0.25:
        return 0.0
    if score <= 0.75:
        return 0.5
    return 1.0


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9']*", str(text or ""))
