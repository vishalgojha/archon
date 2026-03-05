"""Agent recruitment and role routing for orchestration tasks."""

from __future__ import annotations

from dataclasses import dataclass

from archon.agents import (
    CriticAgent,
    DevilsAdvocateAgent,
    FactCheckerAgent,
    ResearcherAgent,
    SynthesizerAgent,
)
from archon.providers import ProviderRouter


@dataclass(slots=True)
class DebateSwarm:
    """The mandatory debate cohort required for truthful outputs."""

    researcher: ResearcherAgent
    critic: CriticAgent
    devils_advocate: DevilsAdvocateAgent
    fact_checker: FactCheckerAgent
    synthesizer: SynthesizerAgent


class SwarmRouter:
    """Constructs the best-fit agent set for each orchestration node.

    Example:
        >>> swarm = router.build_debate_swarm()
        >>> swarm.researcher.name
        'ResearcherAgent'
    """

    def __init__(self, provider_router: ProviderRouter) -> None:
        self.provider_router = provider_router

    def build_debate_swarm(self) -> DebateSwarm:
        """Return the default adversarial truth swarm."""

        return DebateSwarm(
            researcher=ResearcherAgent(self.provider_router),
            critic=CriticAgent(self.provider_router),
            devils_advocate=DevilsAdvocateAgent(self.provider_router),
            fact_checker=FactCheckerAgent(self.provider_router),
            synthesizer=SynthesizerAgent(self.provider_router),
        )
