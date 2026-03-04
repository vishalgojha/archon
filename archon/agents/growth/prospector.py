"""Prospector agent for autonomous opportunity discovery."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.growth.contracts import GrowthAction, serialize_actions


class ProspectorAgent(BaseAgent):
    """Discovers net-new demand signals before competitors.

    Example:
        >>> result = await prospector.run("Increase SMB trials", {"market": "India"}, "task-1")
        >>> result.role
        'fast'
    """

    role = "fast"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        market = context.get("market", "SMB automation buyers in Tier 2/3 cities")
        icp = context.get("icp", "manual-work-heavy businesses using legacy software")
        prompt = (
            "You are ProspectorAgent.\n"
            f"Goal: {goal}\n"
            f"Market: {market}\n"
            f"Current ICP: {icp}\n"
            "Find high-intent lead signals from:\n"
            "- hiring surges for manual operator roles\n"
            "- poor reviews mentioning repetitive tasks\n"
            "- no-chat / no-AI websites with support overload\n"
            "Return a ranked opportunity list with reasons."
        )
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt="Prioritize lead quality and evidence-backed opportunity indicators.",
        )

        actions = [
            GrowthAction(
                action_id="prospect-1",
                owner_agent=self.name,
                objective="Pull top 100 businesses with recent operator hiring spikes.",
                channel=None,
                priority=1,
                reason="Hiring for repetitive tasks is a direct automation pain signal.",
                success_metric=">=35% of contacts confirm manual process bottlenecks.",
                guardrails=["Use public and compliant data sources only."],
            ),
            GrowthAction(
                action_id="prospect-2",
                owner_agent=self.name,
                objective="Create watchlist from software reviews complaining about manual work.",
                channel=None,
                priority=2,
                reason="Review text reveals urgency and migration readiness.",
                success_metric="Generate >=25 SQLs from review-driven outreach in 30 days.",
                guardrails=["No scraping of private groups without permission."],
            ),
        ]

        return AgentResult(
            agent=self.name,
            role=self.role,
            output=response.text,
            confidence=73,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "cost_usd": response.usage.cost_usd,
                "pipeline_stage": "discovery",
                "actions": serialize_actions(actions),
            },
        )

