"""Synthesizer agent: assembles final output with confidence score."""

from __future__ import annotations

import re
from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent


class SynthesizerAgent(BaseAgent):
    """Combines debate outputs into final answer + confidence.

    Example:
        >>> result = await synthesizer.run("...", {"research": "...", "critic": "..."}, "task-1")
        >>> 0 <= result.confidence <= 100
        True
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        prompt = (
            "You are the Synthesizer.\n"
            f"Goal: {goal}\n"
            "Researcher:\n"
            f"{context.get('research', '')}\n\n"
            "Critic:\n"
            f"{context.get('critic', '')}\n\n"
            "DevilsAdvocate:\n"
            f"{context.get('devils_advocate', '')}\n\n"
            "FactChecker:\n"
            f"{context.get('fact_checker', '')}\n\n"
            "Produce:\n"
            "1) final answer\n"
            "2) dissent summary\n"
            "3) confidence: <0-100>"
        )
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt="Keep dissent visible and quantify residual uncertainty.",
        )
        confidence = _extract_confidence(response.text) or 76
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=response.text,
            confidence=confidence,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "cost_usd": response.usage.cost_usd,
            },
        )


def _extract_confidence(text: str) -> int | None:
    match = re.search(r"confidence\s*[:=-]\s*(\d{1,3})", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = int(match.group(1))
    return max(0, min(100, value))
