"""Growth marketing domain agent for ARCHON."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent

SYSTEM_PROMPT = """
You are ARCHON's Growth and Marketing agent, built for Indian D2C brands, SaaS startups,
and digital-first businesses.

Your job is to turn business goals into campaign briefs, content plans, and performance
intelligence — ready for execution.

Outcomes you produce:
- Campaign brief generation (objective, audience, channels, KPIs, budget split)
- Ad copy variants for Meta, Google, and LinkedIn
- Content calendar generation (weekly/monthly)
- SEO brief drafts for blog and landing pages
- Performance report commentary from raw metrics
- A/B test hypothesis generation with success criteria
- WhatsApp broadcast message drafts

Tailor output to Indian consumer behaviour and platform norms where relevant.
Use INR for budgets. Flag channel suitability by audience segment.
Output JSON briefs unless prose copy is requested.
"""


class GrowthMarketingAgent(BaseAgent):
    """Growth and marketing planning for Indian digital businesses.

    Example:
        >>> result = await agent.run("Build campaign brief", {}, "task-1")
        >>> result.role
        'primary'
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run a growth marketing domain task.

        Example:
            >>> result = await agent.run("Ad copy", {"channel": "Meta"}, "task-1")
            >>> result.metadata["sector"]
            'growth_marketing'
        """

        prompt = f"Goal: {goal}\n" f"Context: {context}\n" f"{SYSTEM_PROMPT}"
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt=SYSTEM_PROMPT,
        )
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=response.text,
            confidence=85,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "cost_usd": response.usage.cost_usd,
                "sector": "growth_marketing",
            },
        )
