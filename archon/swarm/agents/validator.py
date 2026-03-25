"""Validator agent for factual cross-checking."""

from __future__ import annotations

from dataclasses import dataclass

from archon.swarm.agents.base import BaseAgent
from archon.swarm.types import AgentResult


@dataclass(slots=True)
class ValidatorAgent(BaseAgent):
    async def run(self, *, goal: str, task_id: str) -> AgentResult:
        context = self.memory.get_context_for_agent(self.name)
        prompt = (
            "Validate the following agent outputs for factual consistency and missing steps. "
            "Flag contradictions or uncertainties. Provide a short checklist.\n\n"
            f"Goal: {goal}\n\n"
            f"Outputs: {context.get('agent_outputs', [])}"
        )
        response_text, usage = await self.ask_model(
            prompt=prompt,
            role="fast",
            system_prompt="You are a factual validator. Do not rewrite the final answer.",
            task_id=task_id,
        )
        return AgentResult(
            agent_id=self.agent_id,
            agent_type=self.name,
            status="DONE",
            output=response_text,
            confidence=0.65,
            usage={
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "cost_usd": usage.cost_usd,
            },
        )
