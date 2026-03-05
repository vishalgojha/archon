"""Shared contracts for ARCHON Growth Swarm planning outputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

OutreachChannel = Literal["whatsapp_sms", "email", "linkedin", "in_app", "voice", "partner"]


@dataclass(slots=True)
class GrowthAction:
    """Single executable recommendation produced by a growth agent."""

    action_id: str
    owner_agent: str
    objective: str
    channel: OutreachChannel | None
    priority: int
    reason: str
    success_metric: str
    guardrails: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FunnelSignal:
    """Observed metric movement that may require a growth intervention."""

    stage: str
    metric: str
    value: float
    trend: str
    note: str


def serialize_actions(actions: list[GrowthAction]) -> list[dict[str, Any]]:
    """Convert dataclass actions into metadata-safe dictionaries."""

    return [asdict(action) for action in actions]
