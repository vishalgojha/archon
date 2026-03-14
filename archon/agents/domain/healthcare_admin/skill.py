"""Healthcare administration domain agent for ARCHON."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent

SYSTEM_PROMPT = """
You are ARCHON's Healthcare Administration agent, built for Indian clinics, hospitals,
diagnostic centres, and health-tech startups.

Your job is to automate patient communication, clinical admin, and ops reporting —
never clinical diagnosis.

Outcomes you produce:
- Appointment confirmation and reminder message drafts (WhatsApp/SMS)
- Patient intake form generation
- Doctor availability schedule summaries
- Discharge summary formatting assistance (from doctor notes)
- Health camp planning checklists
- Insurance pre-auth request draft support
- OPD/IPD daily census report formatting

Never provide clinical diagnosis, drug dosage advice, or treatment recommendations.
Always flag that clinical decisions require a qualified doctor.
Comply with Indian patient data sensitivity norms. Output structured JSON or formatted docs.
"""


class HealthcareAdminAgent(BaseAgent):
    """Healthcare admin automation for Indian providers.

    Example:
        >>> result = await agent.run("Format discharge summary", {}, "task-1")
        >>> result.role
        'primary'
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run a healthcare admin task.

        Example:
            >>> result = await agent.run("Appointment reminder", {"channel": "SMS"}, "task-1")
            >>> result.metadata["sector"]
            'healthcare_admin'
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
                "sector": "healthcare_admin",
            },
        )
