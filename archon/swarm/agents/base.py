"""Base agent for swarm runtime."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from archon.providers import ProviderRouter
from archon.swarm.types import AgentResult, AgentStatus


@dataclass(slots=True)
class BaseAgent:
    name: str
    router: ProviderRouter
    memory: Any
    agent_id: str = field(default_factory=lambda: f"agent-{uuid.uuid4().hex[:8]}")
    status: AgentStatus = "RUNNING"

    async def run(self, *args: Any, **kwargs: Any) -> AgentResult:
        raise NotImplementedError

    async def ask_model(
        self,
        *,
        prompt: str,
        role: str = "primary",
        system_prompt: str | None = None,
        task_id: str | None = None,
    ) -> tuple[str, dict[str, int]]:
        response = await self.router.invoke(
            role=role,
            prompt=prompt,
            system_prompt=system_prompt,
            task_id=task_id,
        )
        usage = response.usage
        return response.text, usage

    def signal_need_help(self, reason: str) -> AgentResult:
        self.status = "NEED_HELP"
        return AgentResult(
            agent_id=self.agent_id,
            agent_type=self.name,
            status=self.status,
            output="",
            confidence=0.0,
            reason=reason,
        )
