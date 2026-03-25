"""Shared types for the self-evolving swarm runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

AgentStatus = Literal["RUNNING", "DONE", "FAILED", "NEED_HELP"]


@dataclass(slots=True)
class AgentSpec:
    agent_type: str
    role: str | None = None
    skill: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResult:
    agent_id: str
    agent_type: str
    status: AgentStatus
    output: str
    confidence: float
    tool_name: str | None = None
    follow_up_needed: bool = False
    reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Plan:
    goal: str
    steps: list[str]
    skills: list[str]
    needs_validation: bool
    notes: str = ""


@dataclass(slots=True)
class SwarmResult:
    task_id: str
    goal: str
    final_answer: str
    confidence: int
    agent_manifest: list[AgentSpec]
    agent_results: list[AgentResult]
    success: bool
    duration_seconds: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PoolState:
    task_id: str
    goal: str
    plan: Plan
    agent_results: list[AgentResult]
    active_agents: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
