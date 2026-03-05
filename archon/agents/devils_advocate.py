"""DevilsAdvocate agent: stress-tests the current best answer."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent


class DevilsAdvocateAgent(BaseAgent):
    """Mandatory stress-test agent that always runs.

    Example:
        >>> result = await devils_advocate.run("...", {"current_best": "..."}, "task-1")
        >>> result.role
        'fast'
    """

    role = "fast"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        current_best = context.get("current_best", "")
        prompt = (
            "You are the Devil's Advocate. Stress-test the proposal hard.\n"
            f"Goal: {goal}\n"
            "Current best answer:\n"
            f"{current_best}\n"
            "Find catastrophic failure modes, edge cases, and missing safeguards."
        )
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt="Be adversarial but constructive; propose mitigations.",
        )
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=response.text,
            confidence=70,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "cost_usd": response.usage.cost_usd,
            },
        )
