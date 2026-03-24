"""Researcher agent: produces initial answer and rebuttal drafts."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent


class ResearcherAgent(BaseAgent):
    """Primary research agent.

    Example:
        >>> result = await researcher.run("How to reduce cloud spend?", {}, "task-1")
        >>> result.role
        'primary'
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        previous = context.get("previous_round")
        critic_feedback = context.get("critic_feedback")

        if critic_feedback:
            prompt = (
                "You are the Researcher in an adversarial debate.\n"
                f"Goal: {goal}\n"
                "Critic feedback to address:\n"
                f"{critic_feedback}\n"
                "Provide a revised answer with explicit assumptions."
            )
        else:
            prompt = (
                "You are the Researcher in an adversarial debate.\n"
                f"Goal: {goal}\n"
                "Return a concise, evidence-oriented first-pass answer."
            )
            if previous:
                prompt += f"\nPrior context:\n{previous}"

        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt="Be explicit about uncertainty and avoid fabricated facts.",
        )
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=response.text,
            confidence=72,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "cost_usd": response.usage.cost_usd,
            },
        )
