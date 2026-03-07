"""Master orchestration runtime for ARCHON task execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from archon.agents.optimization import CostOptimizerAgent
from archon.agents.outbound import EmailAgent, WebChatAgent
from archon.config import ArchonConfig
from archon.core.approval_gate import ApprovalDecision, ApprovalGate
from archon.core.cost_governor import BudgetExceededError, CostGovernor
from archon.core.debate_engine import DebateEngine
from archon.core.growth_router import GrowthSwarmRouter
from archon.core.memory_store import MemoryStore
from archon.core.swarm_router import SwarmRouter
from archon.providers import ProviderRouter

EventSink = Callable[[dict[str, Any]], Awaitable[None]]
TaskMode = Literal["debate", "growth"]


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
    growth: dict[str, Any] | None = None


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
        self.growth_router = GrowthSwarmRouter(self.provider_router)
        self.approval_gate = ApprovalGate()
        self.email_agent = EmailAgent(self.provider_router, self.approval_gate)
        self.webchat_agent = WebChatAgent(self.provider_router, self.approval_gate)
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
                goal=goal, swarm=swarm, task_id=effective_task_id
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
                growth=None,
            )

        if mode == "growth":
            growth_output = await self._run_growth_swarm(
                goal=goal,
                task_id=effective_task_id,
                context=effective_context,
                event_sink=event_sink,
            )
            budget_snapshot = self.cost_governor.snapshot(effective_task_id)

            await self._emit(
                event_sink,
                {
                    "type": "task_completed",
                    "task_id": effective_task_id,
                    "mode": mode,
                    "confidence": growth_output["confidence"],
                    "budget": budget_snapshot,
                },
            )

            await self.memory_store.add_entry(
                task=goal,
                context={
                    "language": language or "auto",
                    "mode": mode,
                    "input_context": effective_context,
                },
                actions_taken=growth_output["actions_taken"],
                causal_reasoning="Seven-agent growth swarm executed for distribution and revenue optimization.",
                actual_outcome=growth_output["final_answer"],
                delta="Growth-mode plan and action recommendations generated.",
                reuse_conditions="Use for sales/distribution strategy and execution planning tasks.",
            )
            self.provider_router.record_task_feedback(
                effective_task_id,
                quality_score=(float(growth_output["confidence"]) / 100.0),
            )

            return OrchestrationResult(
                task_id=effective_task_id,
                goal=goal,
                mode=mode,
                final_answer=growth_output["final_answer"],
                confidence=growth_output["confidence"],
                budget=budget_snapshot,
                debate=None,
                growth=growth_output["payload"],
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

    async def _run_growth_swarm(
        self,
        *,
        goal: str,
        task_id: str,
        context: dict[str, Any],
        event_sink: EventSink | None = None,
    ) -> dict[str, Any]:
        if not self.cost_governor.allow_spawn(task_id, active_agent_count=7):
            raise BudgetExceededError("Budget too constrained to spawn required growth agents.")

        swarm = self.growth_router.build_growth_swarm()
        sequence = [
            swarm.prospector,
            swarm.icp,
            swarm.outreach,
            swarm.nurture,
            swarm.revenue_intel,
            swarm.partner,
            swarm.churn_defense,
        ]

        reports = []
        actions: list[dict[str, Any]] = []
        for agent in sequence:
            result = await agent.run(goal=goal, context=context, task_id=task_id)
            reports.append(result)
            actions.extend(result.metadata.get("actions", []))
            await self._emit(
                event_sink,
                {
                    "type": "growth_agent_completed",
                    "task_id": task_id,
                    "mode": "growth",
                    "agent": result.agent,
                    "confidence": result.confidence,
                },
            )

        confidence = round(sum(result.confidence for result in reports) / len(reports))
        top_actions = sorted(actions, key=lambda item: int(item.get("priority", 99)))[:3]
        summary_bits = [
            str(item.get("objective", "")).strip() for item in top_actions if item.get("objective")
        ]
        summary = (
            "; ".join(summary_bits)
            if summary_bits
            else "No actionable recommendations were generated."
        )
        final_answer = (
            f"Growth swarm completed {len(reports)} agent analyses and generated "
            f"{len(actions)} recommended actions. Top priorities: {summary}"
        )

        payload = {
            "final_answer": final_answer,
            "confidence": confidence,
            "agent_reports": [
                {
                    "agent": result.agent,
                    "role": result.role,
                    "confidence": result.confidence,
                    "output": result.output,
                    "metadata": result.metadata,
                }
                for result in reports
            ],
            "recommended_actions": actions,
        }

        guarded_action = context.get("guarded_action")
        if isinstance(guarded_action, dict):
            action_type = str(guarded_action.get("action_type", "")).strip()
            action_payload = guarded_action.get("payload", {})
            if action_type:
                decision = await self.execute_approved_action(
                    action_type=action_type,
                    payload=action_payload if isinstance(action_payload, dict) else {},
                    event_sink=event_sink,
                )
                payload["guarded_action_decision"] = decision.to_event_payload()

        return {
            "final_answer": final_answer,
            "confidence": confidence,
            "payload": payload,
            "actions_taken": [result.agent for result in reports],
        }
