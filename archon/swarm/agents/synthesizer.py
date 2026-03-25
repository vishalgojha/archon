"""Synthesizer agent that compiles the final response."""

from __future__ import annotations

from dataclasses import dataclass

from archon.swarm.agents.base import BaseAgent
from archon.swarm.types import AgentResult


@dataclass(slots=True)
class SynthesizerAgent(BaseAgent):
    async def run(self, *, goal: str, task_id: str, channel: str = "tui") -> AgentResult:
        context = self.memory.get_context_for_agent(self.name)
        prompt = (
            "Combine the agent outputs into a clear final answer. "
            "Be concise and action-oriented.\n\n"
            f"Goal: {goal}\n\n"
            f"Outputs: {context.get('agent_outputs', [])}\n\n"
            "Provide the final answer only."
        )
        response_text, usage = await self.ask_model(
            prompt=prompt,
            role="primary",
            system_prompt="You are the SynthesizerAgent.",
            task_id=task_id,
        )
        final_text = response_text.strip()
        if channel == "whatsapp":
            final_text = _format_whatsapp(final_text)
        return AgentResult(
            agent_id=self.agent_id,
            agent_type=self.name,
            status="DONE",
            output=final_text,
            confidence=0.75,
            usage={
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "cost_usd": usage.cost_usd,
            },
        )


def _format_whatsapp(text: str, limit: int = 1000) -> str:
    trimmed = text.replace("**", "").replace("`", "")
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[: limit - 3].rstrip() + "..."
