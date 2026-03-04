"""Nurture agent for post-contact conversion acceleration."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.growth.contracts import GrowthAction, serialize_actions


class NurtureAgent(BaseAgent):
    """Re-engages warm leads based on behavioral intent signals.

    Example:
        >>> result = await nurture.run("Reduce drop-offs", {"activation_dropoff": 0.42}, "task-4")
        >>> result.role
        'fast'
    """

    role = "fast"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        funnel_events = context.get("funnel_events", {})
        prompt = (
            "You are NurtureAgent.\n"
            f"Goal: {goal}\n"
            f"Recent behavioral events: {funnel_events}\n"
            "Build event-triggered nurture playbooks for: visited docs, installed-not-activated, and partial feature usage.\n"
            "Each playbook should define trigger, message, wait period, and escalation path."
        )
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt="Favor relevance and timing precision over generic drip campaigns.",
        )

        actions = [
            GrowthAction(
                action_id="nurture-1",
                owner_agent=self.name,
                objective="Trigger activation walkthrough within 15 minutes of stalled onboarding.",
                channel="in_app",
                priority=1,
                reason="Fast contextual guidance materially improves activation completion.",
                success_metric="Increase activation completion by >=12%.",
                guardrails=["Suppress repeat nudges after two ignored attempts."],
            ),
            GrowthAction(
                action_id="nurture-2",
                owner_agent=self.name,
                objective="Send use-case specific re-engagement message for high-intent inactive leads.",
                channel="email",
                priority=2,
                reason="Behavior-matched education outperforms generic reminders.",
                success_metric="Recover >=10% of dormant trial accounts.",
                guardrails=["Exclude leads that opted out from all outbound channels."],
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
                "pipeline_stage": "nurture",
                "actions": serialize_actions(actions),
            },
        )

