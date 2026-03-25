"""SpawnDecider agent for swarm composition."""

from __future__ import annotations

from dataclasses import dataclass

from archon.swarm.types import AgentSpec, PoolState, Plan
from archon.swarm.evolution import EvolutionEngine


@dataclass(slots=True)
class SpawnDeciderAgent:
    plan: Plan
    evolution: EvolutionEngine

    async def decide(self) -> list[AgentSpec]:
        goal_type = self.plan.goal.strip().split()[0].lower() if self.plan.goal else "general"
        best_pattern = self.evolution.get_best_spawn_pattern(goal_type)
        if best_pattern:
            return best_pattern

        deprioritized = set(self.evolution.prune_underperforming_skills())
        manifest: list[AgentSpec] = []
        for skill in self.plan.skills:
            if skill in deprioritized:
                continue
            manifest.append(AgentSpec(agent_type="SkillAgent", skill=skill))

        if not manifest:
            manifest.append(AgentSpec(agent_type="SkillAgent", role="generalist"))

        if self.plan.needs_validation:
            manifest.append(AgentSpec(agent_type="ValidatorAgent"))

        manifest.append(AgentSpec(agent_type="SynthesizerAgent"))
        return manifest

    async def should_spawn_more(self, pool_state: PoolState) -> list[AgentSpec]:
        needs_validation = any(r.status == "NEED_HELP" for r in pool_state.agent_results)
        if not needs_validation:
            return []
        # Add a validator if not already present in results
        if any(r.agent_type == "ValidatorAgent" for r in pool_state.agent_results):
            return []
        return [AgentSpec(agent_type="ValidatorAgent")]
