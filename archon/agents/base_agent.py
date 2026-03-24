"""Base abstractions shared by all ARCHON agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from archon.providers import ProviderResponse, ProviderRouter


@dataclass(slots=True)
class AgentResult:
    """Standard output contract for all agents."""

    agent: str
    role: str
    output: str
    confidence: int
    citations: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base class all ARCHON agents must inherit.

    Example:
        >>> class MyAgent(BaseAgent):
        ...     async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        ...         return AgentResult(agent="my", role="fast", output=goal, confidence=50)
    """

    role: str = "fast"

    def __init__(self, router: ProviderRouter, name: str | None = None) -> None:
        self.router = router
        self.name = name or self.__class__.__name__

    async def ask_model(
        self,
        prompt: str,
        *,
        task_id: str,
        role: str | None = None,
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        """Dispatch one provider call through the unified router.

        Example:
            >>> response = await agent.ask_model("Analyze this", task_id="t1")
            >>> response.provider
            'openai'
        """

        return await self.router.invoke(
            role=role or self.role,
            prompt=prompt,
            task_id=task_id,
            system_prompt=system_prompt,
        )

    @abstractmethod
    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Execute agent-specific reasoning.

        Example:
            >>> result = await agent.run(goal="...", context={}, task_id="task-1")
            >>> result.agent
            'ResearcherAgent'
        """
