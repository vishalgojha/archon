"""Budget enforcement and spend tracking for orchestration tasks."""

from __future__ import annotations

from dataclasses import dataclass


class BudgetExceededError(RuntimeError):
    """Raised when task spend exceeds configured budget."""


@dataclass(slots=True)
class TaskSpendState:
    """In-memory spend state for one orchestration task."""

    budget_usd: float
    spent_usd: float = 0.0
    soft_limit_notified: bool = False


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

        state = TaskSpendState(budget_usd=budget_usd or self.default_budget_usd)
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

    def add_cost(self, task_id: str, cost_usd: float) -> dict[str, float | bool]:
        """Add usage cost and enforce budget thresholds.

        Example:
            >>> report = governor.add_cost("task-1", 0.05)
            >>> report["remaining_usd"] > 0
            True
        """

        state = self._require_state(task_id)
        state.spent_usd = round(state.spent_usd + float(cost_usd), 6)

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
        }

    def snapshot(self, task_id: str) -> dict[str, float | bool]:
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
        }

    def _require_state(self, task_id: str) -> TaskSpendState:
        state = self._tasks.get(task_id)
        if not state:
            raise KeyError(f"Task '{task_id}' is not registered in CostGovernor.")
        return state
