"""Planner agent that breaks goal into steps and relevant skills."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from archon.swarm.agents.base import BaseAgent
from archon.swarm.types import AgentResult, Plan


@dataclass(slots=True)
class PlannerAgent(BaseAgent):
    skills_catalog: dict[str, str] | None = None

    async def run(self, *, goal: str, task_id: str) -> AgentResult:
        catalog = self.skills_catalog or {}
        prompt = _build_prompt(goal, catalog)
        response_text, usage = await self.ask_model(
            prompt=prompt,
            role="fast",
            system_prompt="You are an operations planner for Indian SMB workflows.",
            task_id=task_id,
        )
        plan = _parse_plan(goal, response_text, catalog)
        if plan is None:
            plan = _fallback_plan(goal, catalog)
        self.memory.record_plan(plan)
        return AgentResult(
            agent_id=self.agent_id,
            agent_type=self.name,
            status="DONE",
            output="\n".join(plan.steps),
            confidence=0.7,
            usage={
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "cost_usd": usage.cost_usd,
            },
            metadata={"skills": plan.skills, "needs_validation": plan.needs_validation},
        )


def _build_prompt(goal: str, catalog: dict[str, str]) -> str:
    skills_lines = [f"- {name}: {desc}" for name, desc in catalog.items()]
    skills_block = "\n".join(skills_lines) if skills_lines else "- none"
    return (
        "You are the PlannerAgent. Break the goal into steps and pick relevant skills.\n"
        "Return JSON with keys: steps (list of strings), skills (list of skill names), needs_validation (bool), notes.\n"
        "Only use skill names from the catalog.\n\n"
        f"Goal: {goal}\n\n"
        "Skills Catalog:\n"
        f"{skills_block}\n\n"
        "JSON:"
    )


def _parse_plan(goal: str, text: str, catalog: dict[str, str]) -> Plan | None:
    raw = _extract_json(text)
    if not isinstance(raw, dict):
        return None
    steps = raw.get("steps") if isinstance(raw.get("steps"), list) else []
    steps = [str(step) for step in steps if str(step).strip()]
    skills = raw.get("skills") if isinstance(raw.get("skills"), list) else []
    skills = [str(skill) for skill in skills if str(skill).strip()]
    skills = [skill for skill in skills if skill in catalog]
    needs_validation = bool(raw.get("needs_validation", False))
    notes = str(raw.get("notes", ""))
    if not steps:
        steps = [goal]
    return Plan(
        goal=goal, steps=steps, skills=skills, needs_validation=needs_validation, notes=notes
    )


def _fallback_plan(goal: str, catalog: dict[str, str]) -> Plan:
    goal_lower = goal.lower()
    skills = [name for name in catalog if name.replace("-", " ") in goal_lower]
    return Plan(goal=goal, steps=[goal], skills=skills, needs_validation=False, notes="heuristic")


def _extract_json(text: str) -> dict[str, Any] | None:
    body = text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        body = "\n".join(lines).strip()
    if "{" not in body or "}" not in body:
        return None
    candidate = body[body.find("{") : body.rfind("}") + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
