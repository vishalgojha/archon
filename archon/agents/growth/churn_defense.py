"""Churn defense agent for proactive retention interventions."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.growth.contracts import GrowthAction, serialize_actions


class ChurnDefenseAgent(BaseAgent):
    """Detects disengagement risk and triggers save-playbooks.

    Example:
        >>> result = await churn.run("Reduce churn", {"risk_accounts": []}, "task-7")
        >>> result.role
        'fast'
    """

    role = "fast"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        risk_accounts = context.get("risk_accounts", [])
        prompt = (
            "You are ChurnDefenseAgent.\n"
            f"Goal: {goal}\n"
            f"At-risk account summary: {risk_accounts}\n"
            "Detect top churn drivers from usage drop, ticket tone, and competitor mentions.\n"
            "Return account-priority save plays and escalation criteria."
        )
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt="Focus on timely interventions with measurable retention impact.",
        )

        actions = [
            GrowthAction(
                action_id="churn-1",
                owner_agent=self.name,
                objective="Trigger save sequence for accounts with >30% weekly usage decline.",
                channel="email",
                priority=1,
                reason="Rapid usage decay strongly predicts near-term cancellation.",
                success_metric="Recover >=25% of high-risk accounts before renewal.",
                guardrails=["Escalate strategic accounts to human CSM within 24h."],
            ),
            GrowthAction(
                action_id="churn-2",
                owner_agent=self.name,
                objective="Offer targeted feature enablement session before discounting.",
                channel="voice",
                priority=2,
                reason="Value realization often beats early price concessions.",
                success_metric="Reduce discount-led saves to <35% of rescue cases.",
                guardrails=["Never promise roadmap items not yet committed."],
            ),
        ]

        return AgentResult(
            agent=self.name,
            role=self.role,
            output=response.text,
            confidence=75,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "cost_usd": response.usage.cost_usd,
                "pipeline_stage": "retention",
                "actions": serialize_actions(actions),
            },
        )
