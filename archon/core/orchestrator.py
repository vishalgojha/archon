"""Master orchestration runtime for ARCHON task execution."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable

from archon.agents.optimization import CostOptimizerAgent
from archon.config import ArchonConfig
from archon.core.approval_gate import ApprovalDecision, ApprovalGate
from archon.core.cost_governor import BudgetExceededError, CostGovernor
from archon.core.debate_engine import DebateEngine
from archon.core.memory_store import MemoryStore
from archon.core.multimode import PipelineModeExecutor, SingleModeExecutor
from archon.core.swarm_router import SwarmRouter
from archon.core.types import OrchestrationResult, TaskMode
from archon.evolution.audit_trail import AuditEntry, ImmutableAuditTrail
from archon.providers import ProviderRouter
from archon.skills.skill_registry import SkillDefinition, SkillRegistry

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


class Orchestrator:
    """Coordinates planning, debate, synthesis, and memory.

    Example:
        >>> result = await orchestrator.execute(goal="Draft a migration plan")
        >>> result.task_id.startswith("task-")
        True
    """

    def __init__(
        self,
        config: ArchonConfig,
        *,
        audit_trail: ImmutableAuditTrail | None = None,
    ) -> None:
        self.config = config
        self.cost_governor = CostGovernor(default_budget_usd=config.byok.budget_per_task_usd)
        self.provider_router = ProviderRouter(
            config=config,
            cost_governor=self.cost_governor,
        )
        self.cost_optimizer = CostOptimizerAgent(self.provider_router)
        self.provider_router.set_cost_optimizer(self.cost_optimizer)
        self.swarm_router = SwarmRouter(self.provider_router)
        self.approval_gate = ApprovalGate()
        self.debate_engine = DebateEngine()
        self.memory_store = MemoryStore()
        self.skill_registry = SkillRegistry()
        self._owns_audit_trail = audit_trail is None
        self.audit_trail = audit_trail or ImmutableAuditTrail("archon_evolution_audit.sqlite3")

        # Initialize mode executors
        self._single_executor = SingleModeExecutor(
            config=config,
            provider_router=self.provider_router,
            cost_governor=self.cost_governor,
            memory_store=self.memory_store,
            audit_trail=self.audit_trail,
        )
        self._pipeline_executor = PipelineModeExecutor(
            config=config,
            provider_router=self.provider_router,
            cost_governor=self.cost_governor,
            memory_store=self.memory_store,
            audit_trail=self.audit_trail,
        )

    async def execute(
        self,
        *,
        goal: str,
        mode: TaskMode = "debate",
        task_id: str | None = None,
        language: str | None = None,
        context: dict[str, Any] | None = None,
        event_sink: EventSink | None = None,
        skill_override: SkillDefinition | None = None,
        disable_skills: bool = False,
        emit_audit: bool = True,
    ) -> OrchestrationResult:
        """Run a full orchestration cycle for a user goal.

        Example:
            >>> result = await orchestrator.execute(goal="Explain CAP theorem simply", mode="debate")
            >>> isinstance(result.final_answer, str)
            True
        """

        effective_task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
        selected_skill = self._select_skill(
            goal=goal,
            skill_override=skill_override,
            disable_skills=disable_skills,
        )
        budget_override = (
            _budget_for_cost_tier(self.config.byok.budget_per_task_usd, selected_skill)
            if selected_skill
            else None
        )
        self.cost_governor.start_task(effective_task_id, budget_usd=budget_override)
        if selected_skill and selected_skill.provider_preference:
            self.provider_router.set_task_override(
                effective_task_id, provider=selected_skill.provider_preference
            )

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

        try:
            if mode == "debate":
                if not self.cost_governor.allow_spawn(effective_task_id, active_agent_count=5):
                    raise BudgetExceededError(
                        "Budget too constrained to spawn required debate agents."
                    )

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
                    causal_reasoning=(
                        "Adversarial six-round debate chosen for reliability under uncertainty."
                    ),
                    actual_outcome=outcome.final_answer,
                    delta="Debate-mode synthesis generated.",
                    reuse_conditions="Use for tasks requiring high-confidence synthesis.",
                )
                self.provider_router.record_task_feedback(
                    effective_task_id,
                    quality_score=(outcome.confidence / 100.0),
                )

                if emit_audit:
                    await self._append_task_audit(
                        event_type="task_completed",
                        task_id=effective_task_id,
                        goal=goal,
                        mode=mode,
                        confidence=outcome.confidence,
                        budget_snapshot=budget_snapshot,
                        selected_skill=selected_skill,
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

            elif mode == "single":
                return await self._single_executor.execute(
                    goal=goal,
                    task_id=effective_task_id,
                    language=language,
                    context=context,
                )

            elif mode == "pipeline":
                return await self._pipeline_executor.execute(
                    goal=goal,
                    task_id=effective_task_id,
                    language=language,
                    context=context,
                )

            raise ValueError(f"Unsupported orchestration mode: {mode}")
        except Exception as exc:
            if emit_audit:
                await self._append_task_audit(
                    event_type="task_failed",
                    task_id=effective_task_id,
                    goal=goal,
                    mode=mode,
                    confidence=None,
                    budget_snapshot=None,
                    selected_skill=selected_skill,
                    error=str(exc),
                )
            raise
        finally:
            self.provider_router.clear_task_override(effective_task_id)
            self.provider_router.clear_task_routing(effective_task_id)

    async def aclose(self) -> None:
        """Close shared provider resources."""

        await self.provider_router.aclose()
        if self._owns_audit_trail and self.audit_trail is not None:
            self.audit_trail.close()

    async def _emit(self, event_sink: EventSink | None, event: dict[str, Any]) -> None:
        if event_sink:
            await event_sink(event)

    def _select_skill(
        self,
        *,
        goal: str,
        skill_override: SkillDefinition | None,
        disable_skills: bool,
    ) -> SkillDefinition | None:
        if skill_override is not None:
            return skill_override
        if disable_skills:
            return None
        skills_config = getattr(self.config, "skills", None)
        if skills_config is None or not getattr(skills_config, "enabled", False):
            return None
        self.skill_registry.reload()
        match = self.skill_registry.match_skill(goal)
        return match.skill if match else None

    async def _append_task_audit(
        self,
        *,
        event_type: str,
        task_id: str,
        goal: str,
        mode: str,
        confidence: int | None,
        budget_snapshot: dict[str, Any] | None,
        selected_skill: SkillDefinition | None,
        error: str | None = None,
    ) -> None:
        if self.audit_trail is None:
            return
        routing = self.provider_router.task_routing_snapshot(task_id)
        payload: dict[str, Any] = {
            "task_id": task_id,
            "goal": goal,
            "mode": mode,
            "confidence": confidence,
            "budget": budget_snapshot or {},
            "fallback_used": routing.get("fallback_used", False),
            "providers_used": routing.get("providers", []),
            "preferred_provider": routing.get("preferred_provider"),
        }
        if selected_skill is not None:
            payload["skill"] = {
                "name": selected_skill.name,
                "provider_preference": selected_skill.provider_preference,
                "cost_tier": selected_skill.cost_tier,
                "state": selected_skill.state,
                "version": selected_skill.version,
            }
        if error:
            payload["error"] = error
        entry = AuditEntry(
            entry_id=f"audit-{uuid.uuid4().hex[:12]}",
            timestamp=time.time(),
            event_type=event_type,
            workflow_id=f"task:{task_id}",
            actor="orchestrator",
            payload=payload,
            prev_hash="",
            entry_hash="",
        )
        await asyncio.to_thread(self.audit_trail.append, entry)

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


def _budget_for_cost_tier(default_budget: float, skill: SkillDefinition | None) -> float | None:
    if skill is None:
        return None
    tier = str(skill.cost_tier or "standard").strip().lower()
    multipliers = {
        "low": 0.6,
        "standard": 1.0,
        "high": 1.6,
        "premium": 2.0,
    }
    multiplier = multipliers.get(tier, 1.0)
    return round(float(default_budget) * multiplier, 6)
