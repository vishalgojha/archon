"""Adaptive cost optimizer that only downgrades when quality remains stable."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent


@dataclass(slots=True)
class ModelPerformance:
    """Observed performance profile for one role/provider/model tuple.

    Example:
        >>> profile = ModelPerformance(samples=2, total_cost_usd=0.4, total_quality=1.8)
        >>> round(profile.average_cost_usd, 2)
        0.2
    """

    samples: int = 0
    total_cost_usd: float = 0.0
    total_quality: float = 0.0

    @property
    def average_cost_usd(self) -> float:
        """Average observed spend per invocation.

        Example:
            >>> ModelPerformance(samples=2, total_cost_usd=1.0).average_cost_usd
            0.5
        """

        if self.samples <= 0:
            return 0.0
        return self.total_cost_usd / float(self.samples)

    @property
    def average_quality(self) -> float:
        """Average observed normalized quality score.

        Example:
            >>> round(ModelPerformance(samples=2, total_quality=1.5).average_quality, 2)
            0.75
        """

        if self.samples <= 0:
            return 0.0
        return self.total_quality / float(self.samples)


@dataclass(slots=True, frozen=True)
class OptimizationRecommendation:
    """Actionable provider/model downgrade recommendation.

    Example:
        >>> rec = OptimizationRecommendation(
        ...     role="primary",
        ...     from_provider="anthropic",
        ...     from_model="claude-sonnet-4-5",
        ...     to_provider="openrouter",
        ...     to_model="meta-llama/llama-4-maverick:free",
        ...     spend_ratio=0.9,
        ...     estimated_savings_ratio=0.5,
        ...     current_quality=0.9,
        ...     candidate_quality=0.88,
        ...     sample_size=3,
        ...     reason="Budget pressure with stable quality.",
        ... )
        >>> rec.to_provider
        'openrouter'
    """

    role: str
    from_provider: str
    from_model: str
    to_provider: str
    to_model: str
    spend_ratio: float
    estimated_savings_ratio: float
    current_quality: float
    candidate_quality: float
    sample_size: int
    reason: str


@dataclass(slots=True, frozen=True)
class _ObservedSelection:
    task_id: str
    role: str
    provider: str
    model: str
    cost_usd: float


class CostOptimizerAgent(BaseAgent):
    """Learns lower-cost provider/model paths that preserve quality.

    Example:
        >>> from archon.config import ArchonConfig
        >>> from archon.providers import ProviderRouter
        >>> router = ProviderRouter(config=ArchonConfig())
        >>> optimizer = CostOptimizerAgent(router)
        >>> optimizer.observe_selection("task-1", role="primary", provider="openai", model="o3", cost_usd=0.3)
        >>> optimizer.record_task_feedback("task-1", quality_score=0.92)
    """

    role = "fast"

    def __init__(
        self,
        router,
        *,
        pressure_threshold: float = 0.80,
        quality_floor: float = 0.72,
        max_quality_delta: float = 0.05,
        min_samples: int = 2,
        name: str | None = None,
    ) -> None:
        super().__init__(router, name=name or "CostOptimizerAgent")
        self.pressure_threshold = max(0.0, min(1.0, float(pressure_threshold)))
        self.quality_floor = max(0.0, min(1.0, float(quality_floor)))
        self.max_quality_delta = max(0.0, min(1.0, float(max_quality_delta)))
        self.min_samples = max(1, int(min_samples))
        self._profiles: dict[tuple[str, str, str], ModelPerformance] = {}
        self._pending: dict[str, list[_ObservedSelection]] = {}

    def observe_selection(
        self,
        task_id: str,
        *,
        role: str,
        provider: str,
        model: str,
        cost_usd: float,
    ) -> None:
        """Queue one provider/model selection until task quality is known.

        Example:
            >>> optimizer = CostOptimizerAgent(router)
            >>> optimizer.observe_selection("task-1", role="fast", provider="groq", model="llama", cost_usd=0.01)
        """

        normalized_cost = max(0.0, float(cost_usd))
        observation = _ObservedSelection(
            task_id=str(task_id),
            role=str(role or "").strip().lower() or "primary",
            provider=str(provider or "").strip().lower() or "unknown",
            model=str(model or "").strip() or "unknown",
            cost_usd=normalized_cost,
        )
        self._pending.setdefault(observation.task_id, []).append(observation)

    def record_task_feedback(self, task_id: str, *, quality_score: float) -> None:
        """Finalize queued observations with normalized task quality.

        Example:
            >>> optimizer = CostOptimizerAgent(router)
            >>> optimizer.observe_selection("task-1", role="primary", provider="openai", model="o3", cost_usd=0.2)
            >>> optimizer.record_task_feedback("task-1", quality_score=0.9)
            >>> optimizer.profile_rows(role="primary")[0]["samples"]
            1
        """

        score = max(0.0, min(1.0, float(quality_score)))
        for observation in self._pending.pop(str(task_id), []):
            key = _profile_key(observation.role, observation.provider, observation.model)
            profile = self._profiles.setdefault(key, ModelPerformance())
            profile.samples += 1
            profile.total_cost_usd = round(profile.total_cost_usd + observation.cost_usd, 6)
            profile.total_quality = round(profile.total_quality + score, 6)

    def recommend(
        self,
        *,
        role: str,
        current_provider: str,
        current_model: str,
        spend_snapshot: dict[str, Any] | None = None,
    ) -> OptimizationRecommendation | None:
        """Recommend a cheaper provider/model when spend pressure is high.

        Example:
            >>> optimizer = CostOptimizerAgent(router, min_samples=1)
            >>> optimizer.observe_selection("task-a", role="primary", provider="openai", model="o3", cost_usd=0.3)
            >>> optimizer.record_task_feedback("task-a", quality_score=0.92)
            >>> optimizer.observe_selection("task-b", role="primary", provider="groq", model="llama", cost_usd=0.05)
            >>> optimizer.record_task_feedback("task-b", quality_score=0.9)
            >>> rec = optimizer.recommend(
            ...     role="primary",
            ...     current_provider="openai",
            ...     current_model="o3",
            ...     spend_snapshot={"budget_usd": 1.0, "spent_usd": 0.9},
            ... )
            >>> rec is not None
            True
        """

        spend_ratio = _spend_ratio(spend_snapshot)
        if spend_ratio < self.pressure_threshold:
            return None

        normalized_role = str(role or "").strip().lower() or "primary"
        current_key = _profile_key(normalized_role, current_provider, current_model)
        current_profile = self._profiles.get(current_key)
        if current_profile is None or current_profile.samples < self.min_samples:
            return None

        minimum_quality = max(
            self.quality_floor,
            current_profile.average_quality - self.max_quality_delta,
        )
        current_cost = current_profile.average_cost_usd
        if current_cost <= 0:
            return None

        winner: OptimizationRecommendation | None = None
        for key, candidate in self._profiles.items():
            candidate_role, candidate_provider, candidate_model = key
            if candidate_role != normalized_role:
                continue
            if candidate.samples < self.min_samples:
                continue
            if candidate.average_quality < minimum_quality:
                continue
            if candidate.average_cost_usd >= current_cost:
                continue
            savings_ratio = 1.0 - (candidate.average_cost_usd / current_cost)
            recommendation = OptimizationRecommendation(
                role=normalized_role,
                from_provider=str(current_provider).strip().lower(),
                from_model=str(current_model).strip(),
                to_provider=candidate_provider,
                to_model=candidate_model,
                spend_ratio=round(spend_ratio, 4),
                estimated_savings_ratio=round(max(0.0, savings_ratio), 4),
                current_quality=round(current_profile.average_quality, 4),
                candidate_quality=round(candidate.average_quality, 4),
                sample_size=candidate.samples,
                reason=(
                    "Budget pressure exceeded the downgrade threshold while lower-cost "
                    "historical quality stayed within the configured guardrail."
                ),
            )
            if winner is None or _recommendation_rank(recommendation) < _recommendation_rank(
                winner
            ):
                winner = recommendation
        return winner

    def profile_rows(self, *, role: str | None = None) -> list[dict[str, Any]]:
        """Expose learned cost/quality profiles for inspection and tests.

        Example:
            >>> optimizer = CostOptimizerAgent(router)
            >>> optimizer.profile_rows()
            []
        """

        normalized_role = str(role or "").strip().lower() if role else None
        rows: list[dict[str, Any]] = []
        for (row_role, provider, model), profile in sorted(self._profiles.items()):
            if normalized_role and row_role != normalized_role:
                continue
            rows.append(
                {
                    "role": row_role,
                    "provider": provider,
                    "model": model,
                    "samples": profile.samples,
                    "avg_cost_usd": round(profile.average_cost_usd, 6),
                    "avg_quality": round(profile.average_quality, 6),
                }
            )
        return rows

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Return one human-readable optimization recommendation.

        Example:
            >>> await optimizer.run(
            ...     "reduce spend",
            ...     {
            ...         "selection": {"role": "primary", "provider": "openai", "model": "o3"},
            ...         "spend_snapshot": {"budget_usd": 1.0, "spent_usd": 0.9},
            ...     },
            ...     "task-1",
            ... )
        """

        del goal, task_id
        selection = context.get("selection") if isinstance(context.get("selection"), dict) else {}
        role = (
            str(selection.get("role", context.get("role", "primary"))).strip().lower() or "primary"
        )
        provider = str(selection.get("provider", "")).strip().lower()
        model = str(selection.get("model", "")).strip()
        recommendation = self.recommend(
            role=role,
            current_provider=provider,
            current_model=model,
            spend_snapshot=(
                context.get("spend_snapshot")
                if isinstance(context.get("spend_snapshot"), dict)
                else None
            ),
        )

        if recommendation is None:
            return AgentResult(
                agent=self.name,
                role=self.role,
                output="No downgrade applied. Either spend pressure is low or no safe cheaper profile exists yet.",
                confidence=68,
                metadata={"recommendation": None, "profiles": self.profile_rows(role=role)},
            )

        output = (
            f"Switch {recommendation.role} from {recommendation.from_provider}/"
            f"{recommendation.from_model} to {recommendation.to_provider}/"
            f"{recommendation.to_model} for an estimated "
            f"{recommendation.estimated_savings_ratio * 100:.1f}% cost reduction."
        )
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=output,
            confidence=84,
            metadata={
                "recommendation": asdict(recommendation),
                "profiles": self.profile_rows(role=role),
            },
        )


def _profile_key(role: str, provider: str, model: str) -> tuple[str, str, str]:
    return (
        str(role or "").strip().lower() or "primary",
        str(provider or "").strip().lower() or "unknown",
        str(model or "").strip() or "unknown",
    )


def _recommendation_rank(
    recommendation: OptimizationRecommendation,
) -> tuple[float, float, str, str]:
    return (
        -float(recommendation.estimated_savings_ratio),
        -float(recommendation.candidate_quality),
        recommendation.to_provider,
        recommendation.to_model,
    )


def _spend_ratio(snapshot: dict[str, Any] | None) -> float:
    if not isinstance(snapshot, dict):
        return 0.0
    budget = float(snapshot.get("budget_usd", 0.0) or 0.0)
    spent = float(snapshot.get("spent_usd", 0.0) or 0.0)
    if budget <= 0:
        return 0.0
    return max(0.0, spent / budget)
