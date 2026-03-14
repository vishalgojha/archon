"""Domain skill registry for ARCHON sector agents."""

from archon.agents.domain.education.skill import EducationAgent
from archon.agents.domain.finance_cfo.skill import FinanceCFOAgent
from archon.agents.domain.growth_marketing.skill import GrowthMarketingAgent
from archon.agents.domain.healthcare_admin.skill import HealthcareAdminAgent
from archon.agents.domain.hr_ops.skill import HROpsAgent
from archon.agents.domain.legal.skill import LegalAgent
from archon.agents.domain.logistics.skill import LogisticsAgent
from archon.agents.domain.real_estate.skill import RealEstateAgent

SKILL_REGISTRY: dict[str, type] = {
    "real_estate": RealEstateAgent,
    "legal": LegalAgent,
    "finance_cfo": FinanceCFOAgent,
    "hr_ops": HROpsAgent,
    "growth_marketing": GrowthMarketingAgent,
    "healthcare_admin": HealthcareAdminAgent,
    "logistics": LogisticsAgent,
    "education": EducationAgent,
}

__all__ = ["SKILL_REGISTRY"]
