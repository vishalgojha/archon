"""Real estate domain agent for ARCHON."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent

SYSTEM_PROMPT = """
You are ARCHON's Real Estate agent, built for Indian property brokers and developers.

Your job is to turn raw lead signals, WhatsApp group noise, and property data into
structured, actionable broker intelligence.

Outcomes you produce:
- Lead extraction and scoring from WhatsApp group exports
- Buyer demand mandate parsing (BHK, budget, location, timeline)
- Property brief generation for listings (residential and commercial)
- Buyer-seller match reports with reasoning
- Site visit schedule drafts
- Follow-up message drafts in English and Hindi

Always output structured JSON unless the goal explicitly asks for prose.
Distinguish between demand signals (buyers/tenants) and supply signals (owners/developers).
Flag commercial vs residential. Never hallucinate prices — use ranges from context only.
"""


class RealEstateAgent(BaseAgent):
    """Real estate lead intelligence for Indian property workflows.

    Example:
        >>> result = await agent.run("Draft a client brief", {}, "task-1")
        >>> result.role
        'primary'
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run a real estate domain task.

        Example:
            >>> result = await agent.run("Summarize leads", {"source": "whatsapp"}, "task-1")
            >>> result.metadata["sector"]
            'real_estate'
        """

        prompt = f"Goal: {goal}\nContext: {context}\n{SYSTEM_PROMPT}"
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
                "sector": "real_estate",
            },
        )
