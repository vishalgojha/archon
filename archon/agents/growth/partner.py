"""Partner agent for autonomous channel-development workflows."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.growth.contracts import GrowthAction, serialize_actions


class PartnerAgent(BaseAgent):
    """Builds and manages reseller and integration partner pipelines.

    Example:
        >>> result = await partner.run("Expand channel revenue", {"region": "India"}, "task-6")
        >>> result.role
        'primary'
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        region = context.get("region", "India")
        vertical = context.get("vertical", "pharmacy, retail, and local service SMBs")
        prompt = (
            "You are PartnerAgent.\n"
            f"Goal: {goal}\n"
            f"Region: {region}\n"
            f"Priority verticals: {vertical}\n"
            "Design partner pipeline stages: source, qualify, onboard, co-sell, and retain.\n"
            "Include payout model assumptions and fraud controls."
        )
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt="Prioritize trust, partner economics, and long-term channel quality.",
        )

        actions = [
            GrowthAction(
                action_id="partner-1",
                owner_agent=self.name,
                objective="Recruit top 20 local champions with high business-network centrality.",
                channel="partner",
                priority=1,
                reason="Trusted local operators compress adoption cycles in emerging markets.",
                success_metric="Activate >=8 certified partners in 60 days.",
                guardrails=["KYC partners before enabling referral payouts."],
            ),
            GrowthAction(
                action_id="partner-2",
                owner_agent=self.name,
                objective="Launch partner onboarding kit with demo scripts and objection handling.",
                channel="partner",
                priority=2,
                reason="Structured enablement improves partner conversion consistency.",
                success_metric="Partner-led close rate >=18% within first quarter.",
                guardrails=["Require disclosure of paid referral relationships."],
            ),
        ]

        return AgentResult(
            agent=self.name,
            role=self.role,
            output=response.text,
            confidence=74,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "cost_usd": response.usage.cost_usd,
                "pipeline_stage": "partnerships",
                "actions": serialize_actions(actions),
            },
        )
