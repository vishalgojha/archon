"""Core orchestration components.

Exports are loaded lazily to avoid package import cycles.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ApprovalGate",
    "ApprovalDeniedError",
    "ApprovalRequiredError",
    "ApprovalTimeoutError",
    "BudgetExceededError",
    "CostGovernor",
    "Orchestrator",
]


def __getattr__(name: str) -> Any:
    if name in {
        "ApprovalGate",
        "ApprovalDeniedError",
        "ApprovalRequiredError",
        "ApprovalTimeoutError",
    }:
        from archon.core.approval_gate import (
            ApprovalDeniedError,
            ApprovalGate,
            ApprovalRequiredError,
            ApprovalTimeoutError,
        )

        return {
            "ApprovalGate": ApprovalGate,
            "ApprovalDeniedError": ApprovalDeniedError,
            "ApprovalRequiredError": ApprovalRequiredError,
            "ApprovalTimeoutError": ApprovalTimeoutError,
        }[name]
    if name in {"BudgetExceededError", "CostGovernor"}:
        from archon.core.cost_governor import BudgetExceededError, CostGovernor

        return {"BudgetExceededError": BudgetExceededError, "CostGovernor": CostGovernor}[name]
    if name == "Orchestrator":
        from archon.core.orchestrator import Orchestrator

        return Orchestrator
    raise AttributeError(name)
