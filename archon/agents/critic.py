"""Critic agent: attacks assumptions and identifies weak claims."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent


class CriticAgent(BaseAgent):
    """Adversarial critic for gap analysis.

    Example:
        >>> result = await critic.run("Plan migration", {"research_answer": "..."}, "task-1")
        >>> result.agent
        'CriticAgent'
    """

    role = "fast"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        research_answer = context.get("research_answer", "")
        prompt = (
            "You are the Critic in an adversarial truth process.\n"
            f"Goal: {goal}\n"
            "Researcher answer to challenge:\n"
            f"{research_answer}\n"
            "List the top 5 risks, hidden assumptions, and likely errors."
        )
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt="Prioritize factual and logical weaknesses over style.",
        )
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=response.text,
            confidence=68,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "cost_usd": response.usage.cost_usd,
            },
        )
