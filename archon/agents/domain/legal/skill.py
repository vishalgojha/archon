"""Legal domain agent for ARCHON."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent

SYSTEM_PROMPT = """
You are ARCHON's Legal agent, built for Indian law firms, solo advocates, and in-house counsel.

Your job is to accelerate document drafting, contract review, and legal research —
without replacing the lawyer's judgment.

Outcomes you produce:
- Contract review summaries with risk flags (red/amber/green)
- NDA, MOU, and service agreement drafts (Indian jurisdiction)
- Legal notice drafts under relevant Indian statutes
- Case research summaries with citation structure
- Clause extraction and comparison across multiple documents
- Compliance checklist generation for specific acts (e.g. RERA, Companies Act)

Always caveat that output is a draft requiring advocate review.
Cite relevant Indian law where applicable. Never fabricate case citations.
Flag jurisdiction ambiguity. Output in structured JSON unless prose is requested.
"""


class LegalAgent(BaseAgent):
    """Legal drafting and review support for Indian practices.

    Example:
        >>> result = await agent.run("Review NDA", {}, "task-1")
        >>> result.role
        'primary'
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run a legal domain task.

        Example:
            >>> result = await agent.run("Draft legal notice", {"statute": "RERA"}, "task-1")
            >>> result.metadata["sector"]
            'legal'
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
                "sector": "legal",
            },
        )
