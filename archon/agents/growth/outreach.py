"""Outreach agent for autonomous multi-channel campaigns."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.growth.contracts import GrowthAction, serialize_actions


class OutreachAgent(BaseAgent):
    """Designs and executes personalized outreach sequences.

    Example:
        >>> result = await outreach.run("Increase qualified demos", {"sector": "pharmacy"}, "task-3")
        >>> result.role
        'coding'
    """

    role = "coding"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        sector = context.get("sector", "small service businesses")
        language = context.get("language", "English + local vernacular")
        prompt = (
            "You are OutreachAgent.\n"
            f"Goal: {goal}\n"
            f"Target sector: {sector}\n"
            f"Language profile: {language}\n"
            "Design channel-specific messaging for WhatsApp/SMS, email, LinkedIn, in-app nudges, and voice.\n"
            "Output a 14-day cadence with variant tests and handoff criteria."
        )
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt="Be concise, contextual, and compliant; optimize for helpful outreach over volume.",
        )

        actions = [
            GrowthAction(
                action_id="outreach-1",
                owner_agent=self.name,
                objective="Launch multilingual 14-day sequence for top-priority leads.",
                channel="whatsapp_sms",
                priority=1,
                reason="Direct messaging yields the highest response rates in mobile-first markets.",
                success_metric=">=18% reply rate and >=8% demo-booking rate.",
                guardrails=["Honor consent and local communication regulations."],
            ),
            GrowthAction(
                action_id="outreach-2",
                owner_agent=self.name,
                objective="A/B test problem-first vs outcome-first message framing by segment.",
                channel="email",
                priority=2,
                reason="Message resonance differs by buyer maturity.",
                success_metric=">=20% uplift in qualified replies over control.",
                guardrails=["Throttle sends to avoid spam thresholds."],
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
                "pipeline_stage": "engagement",
                "actions": serialize_actions(actions),
            },
        )
