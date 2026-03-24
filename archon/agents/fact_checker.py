"""FactChecker agent: validates claims and flags uncertainty."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent


class FactCheckerAgent(BaseAgent):
    """Cross-checks final claims before synthesis.

    Example:
        >>> result = await checker.run("...", {"candidate_answer": "..."}, "task-1")
        >>> isinstance(result.output, str)
        True
    """

    role = "fast"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        candidate_answer = context.get("candidate_answer", "")
        prompt = (
            "You are the FactChecker.\n"
            f"Goal: {goal}\n"
            "Answer to validate:\n"
            f"{candidate_answer}\n"
            "Mark claims as: verified, likely, uncertain, or unsupported."
        )
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt="Never claim verification without evidence context.",
        )
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=response.text,
            confidence=74,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "cost_usd": response.usage.cost_usd,
            },
        )
