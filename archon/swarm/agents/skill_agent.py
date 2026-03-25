"""Skill agent executes one SMB tool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from archon.swarm.agents.base import BaseAgent
from archon.swarm.tools.registry import ToolRegistry
from archon.swarm.types import AgentResult
from archon.tooling import ToolCallingAgent, ToolRegistry as FunctionToolRegistry
from archon.tooling.adapters import SMBToolAdapter


@dataclass(slots=True)
class SkillAgent(BaseAgent):
    skill_name: str | None = None
    tools: ToolRegistry | None = None

    async def run(self, *, goal: str, task_id: str) -> AgentResult:
        if self.tools is None or not self.skill_name:
            response_text, usage = await self.ask_model(
                prompt=goal,
                role="primary",
                system_prompt="You are a generalist agent for Indian SMB tasks.",
                task_id=task_id,
            )
            return AgentResult(
                agent_id=self.agent_id,
                agent_type=self.name,
                status="DONE",
                output=response_text,
                confidence=0.6,
                tool_name=None,
                usage={
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                    "cost_usd": usage.cost_usd,
                },
            )

        tool = self.tools.get_tool(self.skill_name) if self.tools else None
        if tool is None:
            return AgentResult(
                agent_id=self.agent_id,
                agent_type=self.name,
                status="FAILED",
                output=f"No tool registered for {self.skill_name}",
                confidence=0.0,
                tool_name=self.skill_name,
            )

        context = self.memory.get_context_for_agent(self.name)
        adapter = SMBToolAdapter(tool=tool, context=context)
        tool_registry = FunctionToolRegistry([adapter])
        caller = ToolCallingAgent(
            router=self.router,
            tools=tool_registry,
            role="primary",
            system_prompt="Use tools when helpful to answer the user request.",
        )
        tool_result = await caller.run(goal=goal, task_id=task_id)
        return AgentResult(
            agent_id=self.agent_id,
            agent_type=self.name,
            status="DONE",
            output=tool_result.final_answer,
            confidence=0.7,
            tool_name=self.skill_name,
        )
