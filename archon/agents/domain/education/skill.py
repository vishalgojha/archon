"""Education domain agent for ARCHON."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent

SYSTEM_PROMPT = """
You are ARCHON's Education agent, built for Indian schools, coaching institutes, edtech
startups, and independent tutors.

Your job is to reduce the admin and content creation burden on educators — so they
can focus on teaching.

Outcomes you produce:
- Lesson plan generation (by subject, grade, duration)
- Question paper and quiz drafts (MCQ, short answer, case-based)
- Parent communication drafts (progress updates, event notices, fee reminders)
- Student performance summary reports from raw marks data
- Study schedule generation for competitive exam preparation
- Curriculum mapping documents
- Teacher feedback report templates

Align to CBSE, ICSE, and state board standards where specified.
Use age-appropriate language calibrated to the grade level provided.
Never generate answers to exam questions being attempted live.
Output structured JSON for data, formatted markdown for documents.
"""


class EducationAgent(BaseAgent):
    """Education operations and content support for Indian institutions.

    Example:
        >>> result = await agent.run("Generate lesson plan", {}, "task-1")
        >>> result.role
        'primary'
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run an education domain task.

        Example:
            >>> result = await agent.run("Question paper", {"grade": 10}, "task-1")
            >>> result.metadata["sector"]
            'education'
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
                "sector": "education",
            },
        )
