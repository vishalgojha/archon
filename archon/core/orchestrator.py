"""Master orchestration runtime for ARCHON task execution."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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

DEFAULT_GROWTH_AGENT_TIMEOUT_S = 120.0


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
        agents = {
            "prospector": swarm.prospector,
            "icp": swarm.icp,
            "outreach": swarm.outreach,
            "nurture": swarm.nurture,
            "revenue_intel": swarm.revenue_intel,
            "partner": swarm.partner,
            "churn_defense": swarm.churn_defense,
        }

        timeout_per_agent_s_raw = context.get(
            "growth_timeout_per_agent_s",
            DEFAULT_GROWTH_AGENT_TIMEOUT_S,
        )
        try:
            timeout_per_agent_s = max(1.0, float(timeout_per_agent_s_raw))
        except (TypeError, ValueError):
            timeout_per_agent_s = DEFAULT_GROWTH_AGENT_TIMEOUT_S

        from archon.agents.base_agent import AgentResult as GrowthAgentResult

        def _stamp_metadata(
            result: GrowthAgentResult,
            *,
            status: str,
            started_at: datetime,
            duration_ms: float,
            error: str | None = None,
            depends_on: list[str] | None = None,
        ) -> None:
            result.metadata.setdefault("actions", [])
            result.metadata["swarm_status"] = status
            result.metadata["swarm_started_at"] = started_at.astimezone(timezone.utc).isoformat()
            result.metadata["swarm_duration_ms"] = round(float(duration_ms), 3)
            if depends_on:
                result.metadata["swarm_depends_on"] = list(depends_on)
            if error:
                result.metadata["swarm_error"] = str(error)

        def _is_complete(result: GrowthAgentResult | None) -> bool:
            if result is None:
                return False
            return str(result.metadata.get("swarm_status", "complete")).lower() == "complete"

        async def _run_agent(
            key: str,
            *,
            extra_context: dict[str, Any] | None = None,
            depends_on: list[str] | None = None,
        ) -> GrowthAgentResult:
            agent = agents[key]
            started_at = datetime.now(tz=timezone.utc)
            agent_name = getattr(agent, "name", getattr(agent, "agent", agent.__class__.__name__))
            role = getattr(agent, "role", "fast")

            await self._emit(
                event_sink,
                {
                    "type": "agent_start",
                    "task_id": task_id,
                    "mode": "growth",
                    "agent": agent_name,
                },
            )

            merged_context = dict(context)
            if extra_context:
                merged_context.update(extra_context)

            try:
                result = await asyncio.wait_for(
                    agent.run(goal=goal, context=merged_context, task_id=task_id),
                    timeout=timeout_per_agent_s,
                )
                duration_ms = (datetime.now(tz=timezone.utc) - started_at).total_seconds() * 1000.0
                _stamp_metadata(
                    result,
                    status="complete",
                    started_at=started_at,
                    duration_ms=duration_ms,
                    depends_on=depends_on,
                )
                await self._emit(
                    event_sink,
                    {
                        "type": "agent_end",
                        "task_id": task_id,
                        "mode": "growth",
                        "agent": result.agent,
                        "role": result.role,
                        "status": "done",
                        "confidence": result.confidence,
                        "output_preview": " ".join(str(result.output).split())[:88],
                    },
                )
                await self._emit(
                    event_sink,
                    {
                        "type": "growth_agent_completed",
                        "task_id": task_id,
                        "mode": "growth",
                        "agent": result.agent,
                        "confidence": result.confidence,
                        "status": "done",
                    },
                )
                return result
            except asyncio.TimeoutError:
                duration_ms = (datetime.now(tz=timezone.utc) - started_at).total_seconds() * 1000.0
                failed = GrowthAgentResult(
                    agent=str(agent_name),
                    role=str(role),
                    output="",
                    confidence=0,
                    metadata={},
                )
                _stamp_metadata(
                    failed,
                    status="failed",
                    started_at=started_at,
                    duration_ms=duration_ms,
                    error=f"Timeout after {timeout_per_agent_s:.0f}s",
                    depends_on=depends_on,
                )
                await self._emit(
                    event_sink,
                    {
                        "type": "agent_end",
                        "task_id": task_id,
                        "mode": "growth",
                        "agent": failed.agent,
                        "role": failed.role,
                        "status": "failed",
                        "confidence": failed.confidence,
                        "output_preview": "",
                    },
                )
                await self._emit(
                    event_sink,
                    {
                        "type": "growth_agent_completed",
                        "task_id": task_id,
                        "mode": "growth",
                        "agent": failed.agent,
                        "confidence": 0,
                        "status": "failed",
                    },
                )
                return failed
            except Exception as exc:  # noqa: BLE001 - isolate agent errors
                duration_ms = (datetime.now(tz=timezone.utc) - started_at).total_seconds() * 1000.0
                failed = GrowthAgentResult(
                    agent=str(agent_name),
                    role=str(role),
                    output="",
                    confidence=0,
                    metadata={},
                )
                _stamp_metadata(
                    failed,
                    status="failed",
                    started_at=started_at,
                    duration_ms=duration_ms,
                    error=str(exc),
                    depends_on=depends_on,
                )
                await self._emit(
                    event_sink,
                    {
                        "type": "agent_end",
                        "task_id": task_id,
                        "mode": "growth",
                        "agent": failed.agent,
                        "role": failed.role,
                        "status": "failed",
                        "confidence": failed.confidence,
                        "output_preview": "",
                    },
                )
                await self._emit(
                    event_sink,
                    {
                        "type": "growth_agent_completed",
                        "task_id": task_id,
                        "mode": "growth",
                        "agent": failed.agent,
                        "confidence": 0,
                        "status": "failed",
                    },
                )
                return failed

        async def _skipped_result(
            key: str,
            *,
            reason: str,
            depends_on: list[str] | None = None,
        ) -> GrowthAgentResult:
            agent = agents[key]
            started_at = datetime.now(tz=timezone.utc)
            agent_name = getattr(agent, "name", getattr(agent, "agent", agent.__class__.__name__))
            role = getattr(agent, "role", "fast")
            skipped = GrowthAgentResult(
                agent=str(agent_name),
                role=str(role),
                output="",
                confidence=0,
                metadata={},
            )
            _stamp_metadata(
                skipped,
                status="skipped",
                started_at=started_at,
                duration_ms=0.0,
                error=reason,
                depends_on=depends_on,
            )
            await self._emit(
                event_sink,
                {
                    "type": "agent_end",
                    "task_id": task_id,
                    "mode": "growth",
                    "agent": skipped.agent,
                    "role": skipped.role,
                    "status": "skipped",
                    "confidence": 0,
                    "output_preview": "",
                },
            )
            await self._emit(
                event_sink,
                {
                    "type": "growth_agent_completed",
                    "task_id": task_id,
                    "mode": "growth",
                    "agent": skipped.agent,
                    "confidence": 0,
                    "status": "skipped",
                },
            )
            return skipped

        results_by_key: dict[str, GrowthAgentResult] = {}

        # Tier 1: Fully independent agents run concurrently.
        tier1 = ["prospector", "icp", "revenue_intel", "partner"]
        tier1_results = await asyncio.gather(*[_run_agent(key) for key in tier1])
        results_by_key.update(dict(zip(tier1, tier1_results, strict=True)))

        # Tier 2: Outreach depends on Prospector + ICP outputs.
        outreach_deps = ["prospector", "icp"]
        if _is_complete(results_by_key.get("prospector")) and _is_complete(
            results_by_key.get("icp")
        ):
            outreach_ctx = {
                "leads": results_by_key["prospector"].output,
                "icp_profile": results_by_key["icp"].output,
            }
            results_by_key["outreach"] = await _run_agent(
                "outreach",
                extra_context=outreach_ctx,
                depends_on=outreach_deps,
            )
        else:
            blocked = [name for name in outreach_deps if not _is_complete(results_by_key.get(name))]
            results_by_key["outreach"] = await _skipped_result(
                "outreach",
                reason=f"Blocked by missing upstream outputs: {', '.join(blocked)}",
                depends_on=outreach_deps,
            )

        # Tier 3: Nurture depends on Outreach; ChurnDefense depends on RevenueIntel.
        nurture_deps = ["outreach"]
        churn_deps = ["revenue_intel"]
        tier3_tasks: list[asyncio.Task[GrowthAgentResult]] = []
        tier3_keys: list[str] = []

        if _is_complete(results_by_key.get("outreach")):
            nurture_ctx = {"outreach_sequences": results_by_key["outreach"].output}
            tier3_tasks.append(
                asyncio.create_task(
                    _run_agent("nurture", extra_context=nurture_ctx, depends_on=nurture_deps)
                )
            )
            tier3_keys.append("nurture")
        else:
            results_by_key["nurture"] = await _skipped_result(
                "nurture",
                reason="Blocked by missing upstream outputs: outreach",
                depends_on=nurture_deps,
            )

        if _is_complete(results_by_key.get("revenue_intel")):
            churn_ctx = {"revenue_signals": results_by_key["revenue_intel"].output}
            tier3_tasks.append(
                asyncio.create_task(
                    _run_agent(
                        "churn_defense",
                        extra_context=churn_ctx,
                        depends_on=churn_deps,
                    )
                )
            )
            tier3_keys.append("churn_defense")
        else:
            results_by_key["churn_defense"] = await _skipped_result(
                "churn_defense",
                reason="Blocked by missing upstream outputs: revenue_intel",
                depends_on=churn_deps,
            )

        if tier3_tasks:
            tier3_results = await asyncio.gather(*tier3_tasks)
            for key, result in zip(tier3_keys, tier3_results, strict=True):
                results_by_key[key] = result

        ordered_keys = [
            "prospector",
            "icp",
            "outreach",
            "nurture",
            "revenue_intel",
            "partner",
            "churn_defense",
        ]
        reports = [results_by_key[key] for key in ordered_keys]

        actions: list[dict[str, Any]] = []
        for result in reports:
            if _is_complete(result):
                actions.extend(result.metadata.get("actions", []))

        completed_confidences = [r.confidence for r in reports if _is_complete(r)]
        confidence = (
            round(sum(completed_confidences) / len(completed_confidences))
            if completed_confidences
            else 0
        )
        top_actions = sorted(actions, key=lambda item: int(item.get("priority", 99)))[:3]
        summary_bits = [
            str(item.get("objective", "")).strip() for item in top_actions if item.get("objective")
        ]
        summary = (
            "; ".join(summary_bits)
            if summary_bits
            else "No actionable recommendations were generated."
        )
        succeeded = [r.agent for r in reports if _is_complete(r)]
        failed = [
            r.agent
            for r in reports
            if str(r.metadata.get("swarm_status", "complete")).lower() == "failed"
        ]
        skipped = [
            r.agent
            for r in reports
            if str(r.metadata.get("swarm_status", "complete")).lower() == "skipped"
        ]
        final_answer = (
            f"Growth swarm completed {len(succeeded)} agent analyses "
            f"(failed={len(failed)}, skipped={len(skipped)}) and generated "
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
