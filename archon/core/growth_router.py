"""Growth swarm construction for autonomous sales and distribution."""

from __future__ import annotations

from dataclasses import dataclass

from archon.agents.growth import (
    ChurnDefenseAgent,
    ICPAgent,
    NurtureAgent,
    OutreachAgent,
    PartnerAgent,
    ProspectorAgent,
    RevenueIntelAgent,
)
from archon.providers import ProviderRouter


@dataclass(slots=True)
class GrowthSwarm:
    """The default growth cohort for autonomous revenue workflows."""

    prospector: ProspectorAgent
    icp: ICPAgent
    outreach: OutreachAgent
    nurture: NurtureAgent
    revenue_intel: RevenueIntelAgent
    partner: PartnerAgent
    churn_defense: ChurnDefenseAgent


class GrowthSwarmRouter:
    """Builds the seven-agent growth swarm.

    Example:
        >>> swarm = router.build_growth_swarm()
        >>> swarm.partner.name
        'PartnerAgent'
    """

    def __init__(self, provider_router: ProviderRouter) -> None:
        self.provider_router = provider_router

    def build_growth_swarm(self) -> GrowthSwarm:
        """Return the default autonomous sales and distribution swarm."""

        return GrowthSwarm(
            prospector=ProspectorAgent(self.provider_router),
            icp=ICPAgent(self.provider_router),
            outreach=OutreachAgent(self.provider_router),
            nurture=NurtureAgent(self.provider_router),
            revenue_intel=RevenueIntelAgent(self.provider_router),
            partner=PartnerAgent(self.provider_router),
            churn_defense=ChurnDefenseAgent(self.provider_router),
        )
