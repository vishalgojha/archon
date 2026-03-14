"""HR and operations domain agent for ARCHON."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent

SYSTEM_PROMPT = """
You are ARCHON's HR and Operations agent, built for Indian SMB founders, HR managers,
and operations leads.

Your job is to automate high-frequency HR paperwork and ops coordination — the work
that clogs people's days.

Outcomes you produce:
- Offer letter drafts (compliant with Indian labour law basics)
- Employee onboarding checklist generation
- Payroll query summaries and anomaly flags
- Performance review template generation
- Leave policy documents and FAQ drafts
- SOP drafts for recurring operational processes
- Vendor coordination follow-up message drafts

Always use Indian statutory context (PF, ESIC, gratuity, leave entitlements).
Flag state-specific variations where relevant. Output structured JSON or markdown docs
depending on goal type.
"""


class HROpsAgent(BaseAgent):
    """HR and ops workflow automation for Indian SMB teams.

    Example:
        >>> result = await agent.run("Draft offer letter", {}, "task-1")
        >>> result.role
        'primary'
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run an HR/ops domain task.

        Example:
            >>> result = await agent.run("Onboarding checklist", {"role": "Ops"}, "task-1")
            >>> result.metadata["sector"]
            'hr_ops'
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
                "sector": "hr_ops",
            },
        )
