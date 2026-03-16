"""ARCHON agents."""

from archon.agents.base_agent import AgentResult, BaseAgent
from archon.agents.critic import CriticAgent
from archon.agents.devils_advocate import DevilsAdvocateAgent
from archon.agents.fact_checker import FactCheckerAgent
from archon.agents.optimization import CostOptimizerAgent
from archon.agents.researcher import ResearcherAgent
from archon.agents.synthesizer import SynthesizerAgent

__all__ = [
    "AgentResult",
    "BaseAgent",
    "ResearcherAgent",
    "CriticAgent",
    "DevilsAdvocateAgent",
    "FactCheckerAgent",
    "SynthesizerAgent",
    "CostOptimizerAgent",
]
