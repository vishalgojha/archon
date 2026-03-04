"""Revenue intelligence agent for funnel diagnostics and interventions."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.growth.contracts import FunnelSignal, GrowthAction, serialize_actions


class RevenueIntelAgent(BaseAgent):
    """Monitors funnel health and prescribes autonomous fixes.

    Example:
        >>> result = await intel.run("Improve win rate", {"funnel": {}}, "task-5")
        >>> "signals" in result.metadata
        True
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        funnel = context.get("funnel", {})
        prompt = (
            "You are RevenueIntelAgent.\n"
            f"Goal: {goal}\n"
            f"Funnel metrics snapshot: {funnel}\n"
            "Identify the top bottlenecks by stage, root cause hypothesis, and corrective action.\n"
            "Escalate only when confidence is low or policy requires human approval."
        )
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt="Use metric-driven diagnosis and avoid unsupported causal claims.",
        )

        signals = [
            FunnelSignal(
                stage="trial_to_active",
                metric="activation_rate",
                value=0.38,
                trend="down",
                note="Onboarding friction identified in first-session setup.",
            ),
            FunnelSignal(
                stage="proposal_to_close",
                metric="win_rate",
                value=0.22,
                trend="flat",
                note="Price objection frequency increased in SMB segment.",
            ),
        ]
        actions = [
            GrowthAction(
                action_id="revenue-1",
                owner_agent=self.name,
                objective="Auto-trigger onboarding concierge flow for stalled trials.",
                channel="in_app",
                priority=1,
                reason="Largest measured drop occurs before first value realization.",
                success_metric="Raise trial-to-active conversion to >=50%.",
                guardrails=["Escalate to human if churn-risk account value is high."],
            ),
            GrowthAction(
                action_id="revenue-2",
                owner_agent=self.name,
                objective="Route high-price-objection leads to ROI calculator + case-study script.",
                channel="email",
                priority=2,
                reason="Structured ROI proof shortens decision cycles.",
                success_metric="Improve proposal-to-close win rate by >=6 points.",
                guardrails=["Do not claim ROI figures without auditable assumptions."],
            ),
        ]

        return AgentResult(
            agent=self.name,
            role=self.role,
            output=response.text,
            confidence=77,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "cost_usd": response.usage.cost_usd,
                "pipeline_stage": "optimization",
                "signals": [asdict(signal) for signal in signals],
                "actions": serialize_actions(actions),
            },
        )
