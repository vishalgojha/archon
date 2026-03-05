"""ICP agent for adaptive ideal-customer refinement."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.growth.contracts import GrowthAction, serialize_actions


class ICPAgent(BaseAgent):
    """Rewrites ICP from conversion and retention outcomes.

    Example:
        >>> result = await icp.run("Improve conversion quality", {"wins": []}, "task-2")
        >>> isinstance(result.metadata["actions"], list)
        True
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        wins = context.get("wins", [])
        losses = context.get("losses", [])
        churned = context.get("churned", [])
        prompt = (
            "You are ICPAgent.\n"
            f"Goal: {goal}\n"
            f"Won accounts: {wins}\n"
            f"Lost accounts: {losses}\n"
            f"Churned accounts: {churned}\n"
            "Infer a revised ICP with positive and negative indicators.\n"
            "Return segment scoring logic, disqualifiers, and expected payback period."
        )
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt="Prefer measurable firmographic and behavioral criteria over generic personas.",
        )

        actions = [
            GrowthAction(
                action_id="icp-1",
                owner_agent=self.name,
                objective="Update ICP scorecard with win-rate and activation-time weighted features.",
                channel=None,
                priority=1,
                reason="Static personas underperform in dynamic markets.",
                success_metric="Lift MQL->SQL conversion by >=15% in next 45 days.",
                guardrails=["Do not include protected attributes in scoring."],
            ),
            GrowthAction(
                action_id="icp-2",
                owner_agent=self.name,
                objective="Publish negative ICP rules to suppress low-fit outreach.",
                channel=None,
                priority=2,
                reason="Lowering false positives increases channel efficiency.",
                success_metric="Reduce unqualified demos by >=20%.",
                guardrails=["Require audit log for every disqualification rule change."],
            ),
        ]

        return AgentResult(
            agent=self.name,
            role=self.role,
            output=response.text,
            confidence=76,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "cost_usd": response.usage.cost_usd,
                "pipeline_stage": "targeting",
                "actions": serialize_actions(actions),
            },
        )
