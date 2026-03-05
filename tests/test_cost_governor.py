"""Unit tests for ARCHON budget governance rules."""

from __future__ import annotations

import pytest

from archon.core.cost_governor import BudgetExceededError, CostGovernor


def test_add_cost_reports_soft_limit_transition_once() -> None:
    governor = CostGovernor(default_budget_usd=1.0, soft_limit_ratio=0.8)
    governor.start_task("task-1")

    first = governor.add_cost("task-1", 0.7)
    second = governor.add_cost("task-1", 0.1)
    third = governor.add_cost("task-1", 0.05)

    assert first["soft_limit_hit"] is False
    assert second["soft_limit_hit"] is True
    assert third["soft_limit_hit"] is False


def test_allow_spawn_blocks_when_soft_limit_hit_and_many_agents() -> None:
    governor = CostGovernor(default_budget_usd=1.0, soft_limit_ratio=0.8)
    governor.start_task("task-2")
    governor.add_cost("task-2", 0.8)

    assert governor.allow_spawn("task-2", active_agent_count=3) is True
    assert governor.allow_spawn("task-2", active_agent_count=4) is False


def test_add_cost_raises_if_budget_exceeded() -> None:
    governor = CostGovernor(default_budget_usd=0.5)
    governor.start_task("task-3")

    governor.add_cost("task-3", 0.49)
    with pytest.raises(BudgetExceededError):
        governor.add_cost("task-3", 0.02)


def test_unregistered_task_raises_key_error() -> None:
    governor = CostGovernor()
    with pytest.raises(KeyError):
        governor.snapshot("missing-task")
