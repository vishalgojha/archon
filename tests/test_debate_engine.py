"""Tests for debate engine event emission."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from archon.agents.base_agent import AgentResult
from archon.core.debate_engine import DebateEngine
from archon.core.swarm_router import DebateSwarm


@dataclass
class _FakeAgent:
    agent: str
    role: str
    outputs: list[tuple[str, int]]

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        del goal, context, task_id
        output, confidence = self.outputs.pop(0)
        return AgentResult(
            agent=self.agent,
            role=self.role,
            output=output,
            confidence=confidence,
        )


def test_debate_engine_emits_round_events() -> None:
    engine = DebateEngine()
    swarm = DebateSwarm(
        researcher=_FakeAgent(
            agent="ResearcherAgent",
            role="research",
            outputs=[
                ("Initial evidence gathered.", 72),
                ("Updated synthesis after criticism.", 75),
            ],
        ),
        critic=_FakeAgent(agent="CriticAgent", role="critic", outputs=[("Risk noted.", 68)]),
        devils_advocate=_FakeAgent(
            agent="DevilsAdvocateAgent",
            role="stress-test",
            outputs=[("Edge cases remain.", 70)],
        ),
        fact_checker=_FakeAgent(
            agent="FactCheckerAgent",
            role="validate",
            outputs=[("Claims mostly hold.", 74)],
        ),
        synthesizer=_FakeAgent(
            agent="SynthesizerAgent",
            role="synthesize",
            outputs=[("Final answer ready.", 88)],
        ),
    )
    events: list[dict[str, Any]] = []

    async def _run() -> None:
        await engine.run(
            goal="Design a rollout plan",
            swarm=swarm,
            task_id="task-1",
            event_sink=lambda event: asyncio.sleep(0, result=events.append(event)),
        )

    asyncio.run(_run())

    starts = [event for event in events if event["type"] == "agent_start"]
    ends = [event for event in events if event["type"] == "agent_end"]
    rounds = [event for event in events if event["type"] == "debate_round_completed"]

    assert len(starts) == 6
    assert len(ends) == 6
    assert len(rounds) == 6
    assert [event["round"] for event in rounds] == [1, 2, 3, 4, 5, 6]
    assert starts[0]["agent"] == "ResearcherAgent"
    assert ends[-1]["agent"] == "SynthesizerAgent"
    assert rounds[-1]["output_preview"] == "Final answer ready."
