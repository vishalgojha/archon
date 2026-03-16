"""Master orchestration runtime for ARCHON task execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from archon.agents.optimization import CostOptimizerAgent
from archon.config import ArchonConfig
from archon.core.approval_gate import ApprovalDecision, ApprovalGate
from archon.core.cost_governor import BudgetExceededError, CostGovernor
from archon.core.debate_engine import DebateEngine
from archon.core.memory_store import MemoryStore
from archon.core.swarm_router import SwarmRouter
from archon.providers import ProviderRouter

EventSink = Callable[[dict[str, Any]], Awaitable[None]]
TaskMode = Literal["debate"]


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


class Orchestrator:
    """Coordinates planning, debate, synthesis, and memory.

    Example:
        >>> result = await orchestrator.execute(goal="Draft a migration plan")
        >>> result.task_id.startswith("task-")
        True
    """

    def __init__(self, config: ArchonConfig, live_provider_calls: bool = False) -> None:
        self.config = config
        self.cost_governor = CostGovernor(default_budget_usd=config.byok.budget_per_task_usd)
        self.provider_router = ProviderRouter(
            config=config,
            cost_governor=self.cost_governor,
            live_mode=live_provider_calls,
        )
        self.cost_optimizer = CostOptimizerAgent(self.provider_router)
        self.provider_router.set_cost_optimizer(self.cost_optimizer)
        self.swarm_router = SwarmRouter(self.provider_router)
        self.approval_gate = ApprovalGate()
        self.debate_engine = DebateEngine()
        self.memory_store = MemoryStore()

    async def execute(
        self,
        *,
        goal: str,
        mode: TaskMode = "debate",
        task_id: str | None = None,
        language: str | None = None,
        context: dict[str, Any] | None = None,
        event_sink: EventSink | None = None,
    ) -> OrchestrationResult:
        """Run a full orchestration cycle for a user goal.

        Example:
            >>> result = await orchestrator.execute(goal="Explain CAP theorem simply", mode="debate")
            >>> isinstance(result.final_answer, str)
            True
        """

        effective_task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
        effective_context = context or {}
        self.cost_governor.start_task(effective_task_id)

        await self._emit(
            event_sink,
            {
                "type": "task_started",
                "task_id": effective_task_id,
                "goal": goal,
                "mode": mode,
                "language": language or "auto",
            },
        )

        if mode == "debate":
            if not self.cost_governor.allow_spawn(effective_task_id, active_agent_count=5):
                raise BudgetExceededError("Budget too constrained to spawn required debate agents.")

            swarm = self.swarm_router.build_debate_swarm()
            outcome = await self.debate_engine.run(
                goal=goal,
                swarm=swarm,
                task_id=effective_task_id,
                event_sink=event_sink,
            )
            debate_payload = self.debate_engine.to_event_payload(outcome)
            budget_snapshot = self.cost_governor.snapshot(effective_task_id)

            await self._emit(
                event_sink,
                {
                    "type": "task_completed",
                    "task_id": effective_task_id,
                    "mode": mode,
                    "confidence": outcome.confidence,
                    "budget": budget_snapshot,
                },
            )
            await self._emit(
                event_sink,
                {
                    "type": "cost_update",
                    "task_id": effective_task_id,
                    "mode": mode,
                    "spent": float(budget_snapshot.get("spent_usd", 0.0) or 0.0),
                    "budget": float(budget_snapshot.get("limit_usd", 0.0) or 0.0),
                },
            )

            await self.memory_store.add_entry(
                task=goal,
                context={"language": language or "auto", "mode": mode},
                actions_taken=[r.agent for r in outcome.rounds],
                causal_reasoning="Adversarial six-round debate chosen for reliability under uncertainty.",
                actual_outcome=outcome.final_answer,
                delta="Debate-mode synthesis generated.",
                reuse_conditions="Use for tasks requiring high-confidence synthesis.",
            )
            self.provider_router.record_task_feedback(
                effective_task_id,
                quality_score=(outcome.confidence / 100.0),
            )

            return OrchestrationResult(
                task_id=effective_task_id,
                goal=goal,
                mode=mode,
                final_answer=outcome.final_answer,
                confidence=outcome.confidence,
                budget=budget_snapshot,
                debate=debate_payload,
            )

        raise ValueError(f"Unsupported orchestration mode: {mode}")

    async def aclose(self) -> None:
        """Close shared provider resources."""

        await self.provider_router.aclose()

    async def _emit(self, event_sink: EventSink | None, event: dict[str, Any]) -> None:
        if event_sink:
            await event_sink(event)

    async def execute_approved_action(
        self,
        *,
        action_type: str,
        payload: dict[str, Any],
        event_sink: EventSink | None = None,
        timeout_seconds: float | None = None,
    ) -> ApprovalDecision:
        """Run one approval-gated action decision."""

        decision = await self.approval_gate.guard(
            action_type=action_type,
            payload=payload,
            event_sink=event_sink,
            timeout_seconds=timeout_seconds,
        )
        await self._emit(
            event_sink,
            {
                "type": "approval_resolved",
                "request_id": decision.request_id,
                "action_type": action_type,
                "approved": decision.approved,
                "approver": decision.approver,
            },
        )
        return decision
