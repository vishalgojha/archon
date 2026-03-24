"""SwarmCoordinator entry point for self-evolving swarm runs."""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Awaitable, Callable

from archon.config import ArchonConfig
from archon.core.cost_governor import CostGovernor
from archon.providers import ProviderRouter
from archon.skills.skill_executor import SkillExecutor
from archon.swarm.agents import PlannerAgent, SkillAgent, SynthesizerAgent, ValidatorAgent
from archon.swarm.evolution import EvolutionEngine
from archon.swarm.memory import SwarmMemory
from archon.swarm.spawn_decider import SpawnDeciderAgent
from archon.swarm.tools.registry import ToolRegistry
from archon.swarm.types import AgentResult, AgentSpec, PoolState, SwarmResult

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


class SwarmCoordinator:
    def __init__(
        self,
        *,
        goal: str,
        session_id: str,
        config: ArchonConfig,
        provider_router: ProviderRouter,
        cost_governor: CostGovernor,
        event_sink: EventSink | None = None,
        channel: str = "tui",
        context: dict[str, Any] | None = None,
    ) -> None:
        self.goal = goal
        self.session_id = session_id
        self.config = config
        self.provider_router = provider_router
        self.cost_governor = cost_governor
        self.event_sink = event_sink
        self.channel = channel
        swarm_db_path = os.getenv("ARCHON_SWARM_DB", "archon_swarm.sqlite3")
        self.evolution = EvolutionEngine(db_path=swarm_db_path)
        self.memory = SwarmMemory(session_id=session_id, db_path=swarm_db_path)
        self.memory.set_goal(goal)
        if context:
            for key, value in context.items():
                self.memory.update_shared(key, value)
        self.skill_executor = SkillExecutor(config=config, provider_router=provider_router)
        self.tools = ToolRegistry(self.skill_executor)
        self.agent_pool: list[tuple[AgentSpec, object]] = []

    async def run(self) -> SwarmResult:
        started = time.time()
        task_id = self.session_id
        await self._emit(
            {
                "type": "task_started",
                "task_id": task_id,
                "goal": self.goal,
                "mode": "swarm",
            }
        )

        planner = PlannerAgent(
            name="PlannerAgent",
            router=self.provider_router,
            memory=self.memory,
            skills_catalog={
                name: tool.description for name, tool in self.tools.list_tools().items()
            },
        )
        await self._emit({"type": "agent_spawned", "task_id": task_id, "agent": planner.name})
        plan_result = await self._run_agent(planner, task_id)
        self.memory.record_output(planner.agent_id, plan_result)

        plan = self.memory.plan
        if plan is None:
            plan = _fallback_plan(self.goal)
            self.memory.record_plan(plan)

        decider = SpawnDeciderAgent(plan=plan, evolution=self.evolution)
        manifest = await decider.decide()
        await self._emit(
            {
                "type": "swarm_manifest",
                "task_id": task_id,
                "count": len(manifest),
            }
        )

        agent_results: list[AgentResult] = [plan_result]
        pending: list[AgentSpec] = list(manifest)

        while pending:
            spec = pending.pop(0)
            agent = self._spawn_agent(spec)
            await self._emit(
                {
                    "type": "agent_spawned",
                    "task_id": task_id,
                    "agent": agent.name,
                    "skill": spec.skill,
                }
            )
            result = await self._run_agent(agent, task_id, spec)
            agent_results.append(result)
            self.memory.record_output(agent.agent_id, result)

            if result.status == "NEED_HELP":
                pool_state = PoolState(
                    task_id=task_id,
                    goal=self.goal,
                    plan=plan,
                    agent_results=agent_results,
                    active_agents=[spec.agent_type for spec in pending],
                )
                new_specs = await decider.should_spawn_more(pool_state)
                pending.extend(new_specs)

        final_answer = _select_final_answer(agent_results)
        confidence = _aggregate_confidence(agent_results)
        duration = time.time() - started
        success = bool(final_answer)

        swarm_result = SwarmResult(
            task_id=task_id,
            goal=self.goal,
            final_answer=final_answer,
            confidence=confidence,
            agent_manifest=manifest,
            agent_results=agent_results,
            success=success,
            duration_seconds=duration,
        )

        self.memory.persist()
        await self.evolution.record(self.session_id, swarm_result)

        await self._emit(
            {
                "type": "task_completed",
                "task_id": task_id,
                "mode": "swarm",
                "confidence": confidence,
                "budget": self.cost_governor.snapshot(task_id),
            }
        )
        await self._emit(
            {
                "type": "cost_update",
                "task_id": task_id,
                "mode": "swarm",
                "spent": float(self.cost_governor.snapshot(task_id).get("spent_usd", 0.0)),
                "budget": float(self.cost_governor.snapshot(task_id).get("limit_usd", 0.0)),
            }
        )
        return swarm_result

    async def _run_agent(
        self, agent: object, task_id: str, spec: AgentSpec | None = None
    ) -> AgentResult:
        name = getattr(agent, "name", agent.__class__.__name__)
        skill_name = getattr(agent, "skill_name", None)
        await self._emit(
            {"type": "agent_start", "task_id": task_id, "agent": name, "skill": skill_name}
        )
        try:
            if isinstance(agent, SynthesizerAgent):
                result = await agent.run(goal=self.goal, task_id=task_id, channel=self.channel)
            elif isinstance(agent, SkillAgent):
                result = await agent.run(goal=self.goal, task_id=task_id)
            else:
                result = await agent.run(goal=self.goal, task_id=task_id)
        except Exception as exc:
            result = AgentResult(
                agent_id=getattr(agent, "agent_id", f"agent-{uuid.uuid4().hex[:8]}"),
                agent_type=name,
                status="FAILED",
                output=str(exc),
                confidence=0.0,
                reason="exception",
            )
        await self._emit(
            {
                "type": "agent_end",
                "task_id": task_id,
                "agent": name,
                "status": result.status,
                "confidence": result.confidence,
                "skill": skill_name,
            }
        )
        if result.usage:
            await self._emit(
                {
                    "type": "agent_usage",
                    "task_id": task_id,
                    "agent": name,
                    "usage": result.usage,
                }
            )
        return result

    def _spawn_agent(self, spec: AgentSpec) -> object:
        if spec.agent_type == "SkillAgent":
            return SkillAgent(
                name="SkillAgent",
                router=self.provider_router,
                memory=self.memory,
                skill_name=spec.skill,
                tools=self.tools,
            )
        if spec.agent_type == "ValidatorAgent":
            return ValidatorAgent(
                name="ValidatorAgent",
                router=self.provider_router,
                memory=self.memory,
            )
        if spec.agent_type == "SynthesizerAgent":
            return SynthesizerAgent(
                name="SynthesizerAgent",
                router=self.provider_router,
                memory=self.memory,
            )
        return SkillAgent(
            name="SkillAgent",
            router=self.provider_router,
            memory=self.memory,
            skill_name=spec.skill,
            tools=self.tools,
        )

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.event_sink:
            await self.event_sink(event)


def _select_final_answer(results: list[AgentResult]) -> str:
    synth = next((r for r in results if r.agent_type == "SynthesizerAgent"), None)
    if synth and synth.output:
        return synth.output
    for result in reversed(results):
        if result.output:
            return result.output
    return ""


def _aggregate_confidence(results: list[AgentResult]) -> int:
    values = [r.confidence for r in results if r.confidence]
    if not values:
        return 50
    return int(round(sum(values) / len(values) * 100))


def _fallback_plan(goal: str):
    from archon.swarm.types import Plan

    return Plan(goal=goal, steps=[goal], skills=[], needs_validation=False, notes="fallback")
