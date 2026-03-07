"""Budget enforcement and spend tracking for orchestration tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class BudgetExceededError(RuntimeError):
    """Raised when task spend exceeds configured budget."""


@dataclass(slots=True)
class TaskSpendState:
    """In-memory spend state for one orchestration task."""

    budget_usd: float
    spent_usd: float = 0.0
    soft_limit_notified: bool = False
    cost_by_provider: dict[str, float] | None = None
    cost_by_model: dict[str, float] | None = None
    cost_by_provider_model: dict[str, float] | None = None
    optimizations: list[dict[str, Any]] | None = None


class CostGovernor:
    """Tracks and enforces per-task budget caps.

    Example:
        >>> governor = CostGovernor(default_budget_usd=0.50)
        >>> governor.start_task("task-1")
        >>> governor.add_cost("task-1", 0.10)["spent_usd"]
        0.1
    """

    def __init__(self, default_budget_usd: float = 0.50, soft_limit_ratio: float = 0.80) -> None:
        self.default_budget_usd = default_budget_usd
        self.soft_limit_ratio = soft_limit_ratio
        self._tasks: dict[str, TaskSpendState] = {}

    def start_task(self, task_id: str, budget_usd: float | None = None) -> TaskSpendState:
        """Initialize budget tracking for a task.

        Example:
            >>> state = governor.start_task("task-2", budget_usd=1.0)
            >>> state.budget_usd
            1.0
        """

        state = TaskSpendState(
            budget_usd=budget_usd or self.default_budget_usd,
            cost_by_provider={},
            cost_by_model={},
            cost_by_provider_model={},
            optimizations=[],
        )
        self._tasks[task_id] = state
        return state

    def allow_spawn(self, task_id: str, active_agent_count: int) -> bool:
        """Return whether more agents may be spawned under current budget policy.

        Example:
            >>> governor.allow_spawn("task-1", active_agent_count=2)
            True
        """

        state = self._require_state(task_id)
        if state.spent_usd >= state.budget_usd:
            return False
        if active_agent_count > 3 and state.spent_usd >= (state.budget_usd * self.soft_limit_ratio):
            return False
        return True

    def add_cost(
        self,
        task_id: str,
        cost_usd: float,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, float | bool | dict[str, float]]:
        """Add usage cost and enforce budget thresholds.

        Example:
            >>> report = governor.add_cost("task-1", 0.05, provider="openai", model="gpt-4o")
            >>> report["remaining_usd"] > 0
            True
        """

        state = self._require_state(task_id)
        normalized_cost = float(cost_usd)
        state.spent_usd = round(state.spent_usd + normalized_cost, 6)
        if provider:
            bucket = state.cost_by_provider or {}
            bucket[provider] = round(bucket.get(provider, 0.0) + normalized_cost, 6)
            state.cost_by_provider = bucket
        if model:
            bucket = state.cost_by_model or {}
            bucket[model] = round(bucket.get(model, 0.0) + normalized_cost, 6)
            state.cost_by_model = bucket
        if provider or model:
            composite = f"{provider or 'unknown'}/{model or 'unknown'}"
            bucket = state.cost_by_provider_model or {}
            bucket[composite] = round(bucket.get(composite, 0.0) + normalized_cost, 6)
            state.cost_by_provider_model = bucket

        soft_limit_hit = False
        if not state.soft_limit_notified and state.spent_usd >= (
            state.budget_usd * self.soft_limit_ratio
        ):
            state.soft_limit_notified = True
            soft_limit_hit = True

        if state.spent_usd > state.budget_usd:
            raise BudgetExceededError(
                f"Task '{task_id}' exceeded budget ${state.budget_usd:.2f} "
                f"(spent ${state.spent_usd:.4f})."
            )

        remaining = round(max(0.0, state.budget_usd - state.spent_usd), 6)
        return {
            "budget_usd": state.budget_usd,
            "spent_usd": state.spent_usd,
            "remaining_usd": remaining,
            "soft_limit_hit": soft_limit_hit,
            "cost_by_provider": dict(state.cost_by_provider or {}),
            "cost_by_model": dict(state.cost_by_model or {}),
            "cost_by_provider_model": dict(state.cost_by_provider_model or {}),
            "optimizations": list(state.optimizations or []),
        }

    def record_optimization(self, task_id: str, optimization: dict[str, Any]) -> None:
        """Persist one optimizer action on the task snapshot.

        Example:
            >>> governor = CostGovernor()
            >>> governor.start_task("task-1")
            >>> governor.record_optimization("task-1", {"role": "primary"})
            >>> governor.snapshot("task-1")["optimizations"][0]["role"]
            'primary'
        """

        state = self._require_state(task_id)
        bucket = state.optimizations or []
        bucket.append(dict(optimization))
        state.optimizations = bucket

    def snapshot(self, task_id: str) -> dict[str, Any]:
        """Return current budget snapshot for one task.

        Example:
            >>> governor.snapshot("task-1")["budget_usd"]
            0.5
        """

        state = self._require_state(task_id)
        return {
            "budget_usd": state.budget_usd,
            "spent_usd": state.spent_usd,
            "remaining_usd": round(max(0.0, state.budget_usd - state.spent_usd), 6),
            "soft_limit_notified": state.soft_limit_notified,
            "cost_by_provider": dict(state.cost_by_provider or {}),
            "cost_by_model": dict(state.cost_by_model or {}),
            "cost_by_provider_model": dict(state.cost_by_provider_model or {}),
            "optimizations": list(state.optimizations or []),
        }

    def _require_state(self, task_id: str) -> TaskSpendState:
        state = self._tasks.get(task_id)
        if not state:
            raise KeyError(f"Task '{task_id}' is not registered in CostGovernor.")
        return state
