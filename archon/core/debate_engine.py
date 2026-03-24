"""Adversarial truth layer for multi-round agent debate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from archon.agents import AgentResult
from archon.core.swarm_router import DebateSwarm

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


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

    async def run(
        self,
        goal: str,
        swarm: DebateSwarm,
        task_id: str,
        event_sink: EventSink | None = None,
    ) -> DebateOutcome:
        """Execute the adversarial rounds and return a synthesized result."""

        rounds: list[AgentResult] = []
        total_rounds = 6

        async def emit(event: dict[str, Any]) -> None:
            if event_sink is not None:
                await event_sink(event)

        async def record(result: AgentResult, round_number: int) -> None:
            rounds.append(result)
            await emit(
                {
                    "type": "agent_end",
                    "task_id": task_id,
                    "mode": "debate",
                    "round": round_number,
                    "total_rounds": total_rounds,
                    "agent": result.agent,
                    "role": result.role,
                    "status": "done",
                    "confidence": result.confidence,
                    "output_preview": " ".join(result.output.split())[:88],
                }
            )
            await emit(
                {
                    "type": "debate_round_completed",
                    "task_id": task_id,
                    "mode": "debate",
                    "round": round_number,
                    "total_rounds": total_rounds,
                    "agent": result.agent,
                    "role": result.role,
                    "confidence": result.confidence,
                    "output_preview": " ".join(result.output.split())[:88],
                }
            )

        async def run_round(
            *,
            round_number: int,
            runner,
            context: dict[str, Any],
        ) -> AgentResult:
            await emit(
                {
                    "type": "agent_start",
                    "task_id": task_id,
                    "mode": "debate",
                    "round": round_number,
                    "total_rounds": total_rounds,
                    "agent": getattr(
                        runner,
                        "name",
                        getattr(runner, "agent", runner.__class__.__name__),
                    ),
                }
            )
            result = await runner.run(goal, context=context, task_id=task_id)
            await record(result, round_number)
            return result

        # Round 1: Researcher
        research_1 = await run_round(round_number=1, runner=swarm.researcher, context={})

        # Round 2: Critic attacks
        critic = await run_round(
            round_number=2,
            runner=swarm.critic,
            context={"research_answer": research_1.output},
        )

        # Round 3: Researcher defends/concedes
        research_2 = await run_round(
            round_number=3,
            runner=swarm.researcher,
            context={
                "previous_round": research_1.output,
                "critic_feedback": critic.output,
            },
        )

        # Round 4: Devil's Advocate stress-test
        devils = await run_round(
            round_number=4,
            runner=swarm.devils_advocate,
            context={"current_best": research_2.output},
        )

        # Round 5: Fact-checker validation
        fact_check = await run_round(
            round_number=5,
            runner=swarm.fact_checker,
            context={"candidate_answer": research_2.output},
        )

        # Round 6: Synthesizer
        synth = await run_round(
            round_number=6,
            runner=swarm.synthesizer,
            context={
                "research": research_2.output,
                "critic": critic.output,
                "devils_advocate": devils.output,
                "fact_checker": fact_check.output,
            },
        )

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
