"""Skill executor for ARCHON - wires skill agents to the orchestration flow."""

from __future__ import annotations

from typing import Any

from archon.config import ArchonConfig
from archon.providers import ProviderRouter
from archon.skills.skill_registry import SkillDefinition, SkillRegistry
from archon.skills.india_skills import (
    InsuranceAdvisorAgent,
    VehicleRTOAgent,
    TelecomAssistantAgent,
    LegalAidAgent,
    WaterUtilityAgent,
)
from archon.skills.india_skills_batch2 import (
    CustomsImportAgent,
    ExportComplianceAgent,
    FSSAIComplianceAgent,
    GovtFormAssistantAgent,
    GSTComplianceAgent,
    HealthcareTriageAgent,
    HRRecruitmentAgent,
    KisanAdvisoryAgent,
    MSMELoanAssistantAgent,
    ONDCSellerAssistantAgent,
    PropertyVerificationAgent,
    ScholarshipApplicationAgent,
    SolarAdoptionAgent,
    StartupIndiaAgent,
    UPIFraudDetectionAgent,
    ExplainSimplyTheoremAgent,
)


class SkillExecutor:
    """Executes skill agents when a skill match occurs."""

    def __init__(
        self,
        config: ArchonConfig,
        provider_router: ProviderRouter,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.config = config
        self.provider_router = provider_router
        self.skill_registry = skill_registry or SkillRegistry()
        self._agents: dict[str, Any] = {}
        self._register_agents()

    def _register_agents(self) -> None:
        """Register all skill agents."""
        # Batch 1 agents (from india_skills.py)
        self._agents["insurance-advisor"] = InsuranceAdvisorAgent(self.provider_router, self.config)
        self._agents["vehicle-rto"] = VehicleRTOAgent(self.provider_router, self.config)
        self._agents["telecom-assistant"] = TelecomAssistantAgent(self.provider_router, self.config)
        self._agents["legal-aid"] = LegalAidAgent(self.provider_router, self.config)
        self._agents["water-utility"] = WaterUtilityAgent(self.provider_router, self.config)

        # Batch 2 agents (from india_skills_batch2.py)
        self._agents["customs-import"] = CustomsImportAgent(self.provider_router, self.config)
        self._agents["export-compliance"] = ExportComplianceAgent(self.provider_router, self.config)
        self._agents["fssai-compliance"] = FSSAIComplianceAgent(self.provider_router, self.config)
        self._agents["govt-form-assistant"] = GovtFormAssistantAgent(
            self.provider_router, self.config
        )
        self._agents["gst-compliance"] = GSTComplianceAgent(self.provider_router, self.config)
        self._agents["healthcare-triage"] = HealthcareTriageAgent(self.provider_router, self.config)
        self._agents["hr-recruitment"] = HRRecruitmentAgent(self.provider_router, self.config)
        self._agents["kisan-advisory"] = KisanAdvisoryAgent(self.provider_router, self.config)
        self._agents["msme-loan-assistant"] = MSMELoanAssistantAgent(
            self.provider_router, self.config
        )
        self._agents["ondc-seller-assistant"] = ONDCSellerAssistantAgent(
            self.provider_router, self.config
        )
        self._agents["property-verification"] = PropertyVerificationAgent(
            self.provider_router, self.config
        )
        self._agents["scholarship-application"] = ScholarshipApplicationAgent(
            self.provider_router, self.config
        )
        self._agents["solar-adoption"] = SolarAdoptionAgent(self.provider_router, self.config)
        self._agents["startup-india"] = StartupIndiaAgent(self.provider_router, self.config)
        self._agents["upi-fraud-detection"] = UPIFraudDetectionAgent(
            self.provider_router, self.config
        )
        self._agents["explain-simply-theorem"] = ExplainSimplyTheoremAgent(
            self.provider_router, self.config
        )

    async def execute_skill(
        self,
        skill_name: str,
        goal: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Execute a skill agent for the given goal and context."""
        context = dict(context or {})
        context["goal"] = goal

        agent = self._agents.get(skill_name)
        if agent is None:
            # Fallback to standard provider routing if no agent found
            return await self._fallback_execute(goal, context)

        return await agent.execute(context)

    async def _fallback_execute(
        self,
        goal: str,
        context: dict[str, Any],
    ) -> str:
        """Fallback execution using standard provider routing."""
        prompt = f"Task: {goal}\n\nContext:\n"
        for key, value in context.items():
            if key not in ("goal", "tenant_id", "session_id"):
                prompt += f"- {key}: {value}\n"
        prompt += "\nProvide a clear, concise answer."

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
        )
        return response.text

    def get_agent(self, skill_name: str) -> Any | None:
        """Get a skill agent by name."""
        return self._agents.get(skill_name)

    def list_agents(self) -> list[str]:
        """List all registered agent names."""
        return sorted(self._agents.keys())
