"""Core type definitions for ARCHON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

TaskMode = Literal["debate", "single", "pipeline"]


@dataclass(slots=True)
class OrchestrationResult:
    """Final output payload returned by Orchestrator."""

    task_id: str
    goal: str
    mode: TaskMode
    final_answer: str
    confidence: int
    budget: dict[str, float | bool]
    debate: dict[str, Any] | None = None
