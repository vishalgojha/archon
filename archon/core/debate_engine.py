"""Adversarial truth layer for multi-round agent debate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from archon.agents import AgentResult
from archon.core.swarm_router import DebateSwarm


@dataclass(slots=True)
class DebateOutcome:
    """Final payload emitted by DebateEngine."""

    final_answer: str
    confidence: int
    rounds: list[AgentResult] = field(default_factory=list)
    dissent: list[str] = field(default_factory=list)


class DebateEngine:
    """Runs ARCHON's mandatory six-round adversarial debate.

    Example:
        >>> outcome = await engine.run("How can we lower latency?", swarm, "task-1")
        >>> outcome.confidence >= 0
        True
    """

    async def run(self, goal: str, swarm: DebateSwarm, task_id: str) -> DebateOutcome:
        """Execute the adversarial rounds and return a synthesized result."""

        rounds: list[AgentResult] = []

        # Round 1: Researcher
        research_1 = await swarm.researcher.run(goal, context={}, task_id=task_id)
        rounds.append(research_1)

        # Round 2: Critic attacks
        critic = await swarm.critic.run(
            goal,
            context={"research_answer": research_1.output},
            task_id=task_id,
        )
        rounds.append(critic)

        # Round 3: Researcher defends/concedes
        research_2 = await swarm.researcher.run(
            goal,
            context={
                "previous_round": research_1.output,
                "critic_feedback": critic.output,
            },
            task_id=task_id,
        )
        rounds.append(research_2)

        # Round 4: Devil's Advocate stress-test
        devils = await swarm.devils_advocate.run(
            goal,
            context={"current_best": research_2.output},
            task_id=task_id,
        )
        rounds.append(devils)

        # Round 5: Fact-checker validation
        fact_check = await swarm.fact_checker.run(
            goal,
            context={"candidate_answer": research_2.output},
            task_id=task_id,
        )
        rounds.append(fact_check)

        # Round 6: Synthesizer
        synth = await swarm.synthesizer.run(
            goal,
            context={
                "research": research_2.output,
                "critic": critic.output,
                "devils_advocate": devils.output,
                "fact_checker": fact_check.output,
            },
            task_id=task_id,
        )
        rounds.append(synth)

        dissent = [critic.output, devils.output]
        return DebateOutcome(
            final_answer=synth.output,
            confidence=synth.confidence,
            rounds=rounds,
            dissent=dissent,
        )

    @staticmethod
    def to_event_payload(outcome: DebateOutcome) -> dict[str, Any]:
        """Convert outcome to JSON-safe payload for APIs/WebSockets.

        Example:
            >>> payload = DebateEngine.to_event_payload(outcome)
            >>> "confidence" in payload
            True
        """

        return {
            "final_answer": outcome.final_answer,
            "confidence": outcome.confidence,
            "dissent": outcome.dissent,
            "rounds": [
                {
                    "agent": r.agent,
                    "role": r.role,
                    "confidence": r.confidence,
                    "output": r.output,
                    "metadata": r.metadata,
                }
                for r in outcome.rounds
            ],
        }

