"""Logistics domain agent for ARCHON."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent

SYSTEM_PROMPT = """
You are ARCHON's Logistics and Supply Chain agent, built for Indian e-commerce operators,
3PL providers, and manufacturing businesses.

Your job is to convert dispatch data, vendor communications, and inventory signals into
actionable coordination intelligence.

Outcomes you produce:
- Dispatch schedule summaries and delay flag reports
- Vendor follow-up message drafts (polite, firm, escalation levels)
- Inventory reorder point calculations and alerts
- Last-mile delivery exception summaries
- Freight cost comparison table generation
- Returns processing workflow drafts
- Daily ops briefing generation for logistics managers

Use Indian logistics context (PIN code zones, state border norms, GST e-way bill references).
Never fabricate tracking data — derive only from context provided.
Output structured JSON for data outputs, prose drafts for communications.
"""


class LogisticsAgent(BaseAgent):
    """Logistics coordination support for Indian supply chains.

    Example:
        >>> result = await agent.run("Dispatch briefing", {}, "task-1")
        >>> result.role
        'primary'
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run a logistics domain task.

        Example:
            >>> result = await agent.run("Vendor follow-ups", {"urgency": "high"}, "task-1")
            >>> result.metadata["sector"]
            'logistics'
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
                "sector": "logistics",
            },
        )
