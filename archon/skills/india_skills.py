"""India-specific skill implementations for ARCHON - Skills 16-20."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import BaseAgent
from archon.config import ArchonConfig
from archon.providers import ProviderRouter
from archon.skills.skill_registry import SkillDefinition, SkillRegistry


class InsuranceAdvisorAgent(BaseAgent):
    """Insurance recommendation and claims assistance agent."""

    role = "insurance-advisor"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.insurance_types = {
            "health": "Hospitalization, OPD, critical illness",
            "life": "Term, whole life, endowment, ULIP",
            "motor": "Third-party, comprehensive",
            "crop": "PMFBY crop insurance",
        }
        self.govt_schemes = [
            "PMJJBY (Pradhan Mantri Jeevan Jyoti Bima Yojana)",
            "PMSBY (Pradhan Mantri Suraksha Bima Yojana)",
            "Ayushman Bharat PM-JAY",
            "PMFBY (Crop Insurance)",
        ]

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute insurance advisory assistance."""
        insurance_type = context.get("insurance_type", "health")
        age = context.get("age", 30)
        state = context.get("state", "unknown")
        sum_assured = context.get("sum_assured", "not specified")

        prompt = self._build_insurance_prompt(insurance_type, age, state, sum_assured, context)

        # Use pipeline mode for needs→comparison→recommendation
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_insurance_system_prompt(),
        )

        return self._format_insurance_response(response.text, context)

    def _build_insurance_prompt(
        self,
        insurance_type: str,
        age: int,
        state: str,
        sum_assured: str,
        context: dict[str, Any],
    ) -> str:
        """Build insurance advisory prompt."""
        family_size = context.get("family_size", "not specified")
        budget = context.get("budget_range", "not specified")

        return f"""Insurance Advisor

Insurance Type: {insurance_type}
Age: {age} years
State: {state}
Sum Assured: {sum_assured}
Family Size: {family_size}
Budget: {budget}

Provide:
1. Needs analysis
2. Policy recommendations (3-5 options)
3. Premium comparison table
4. Coverage details (inclusions, exclusions)
5. Enrollment process
6. Claims process
7. Tax benefits (80D, 10(10D))
8. Government schemes (PMJJBY, PMSBY, Ayushman Bharat)
9. Renewal reminders

Include comparison tables and calculations."""

    def _get_insurance_system_prompt(self) -> str:
        """Get insurance system prompt."""
        return """You are an insurance advisor for Indian consumers.
Provide unbiased policy comparisons. Include government schemes.
Always recommend reading policy wordings. Warn about exclusions."""

    def _format_insurance_response(self, content: str, context: dict[str, Any]) -> str:
        """Format insurance response."""
        insurance_type = context.get("insurance_type", "insurance")
        age = context.get("age", "age")
        return f"""💼 Insurance Advisor - {insurance_type} (Age {age})

{content}

🔗 IRDAI: https://www.irdai.gov.in
📞 Policy comparison: Check multiple insurers
⚠️ Read policy wordings before purchase"""


class VehicleRTOAgent(BaseAgent):
    """Vehicle RTO services assistance agent."""

    role = "vehicle-rto"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.services = {
            "RC": "Registration Certificate (new/transfer/renewal)",
            "License": "Learner/Permanent/Renewal",
            "Permit": "National/State/Contract carriage",
            "PUC": "Pollution Under Control certificate",
            "Tax": "Road tax payment",
            "NOC": "No Objection Certificate for inter-state",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute RTO services assistance."""
        vehicle_type = context.get("vehicle_type", "two-wheeler")
        service_type = context.get("service_type", "RC")
        state = context.get("state", "unknown")
        reg_number = context.get("registration_number", "not provided")

        prompt = self._build_rto_prompt(vehicle_type, service_type, state, reg_number, context)

        # Use single mode for quick service guidance
        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt=self._get_rto_system_prompt(),
        )

        return self._format_rto_response(response.text, context)

    def _build_rto_prompt(
        self,
        vehicle_type: str,
        service_type: str,
        state: str,
        reg_number: str,
        context: dict[str, Any],
    ) -> str:
        """Build RTO services prompt."""
        rto_location = context.get("rto_location", "not specified")
        age_of_vehicle = context.get("age_of_vehicle", "not specified")

        return f"""Vehicle RTO Services

Vehicle Type: {vehicle_type}
Service Type: {service_type}
State: {state}
Registration Number: {reg_number}
RTO Location: {rto_location}
Vehicle Age: {age_of_vehicle}

Provide:
1. Service overview
2. Document checklist
3. Application process (Parivahan portal)
4. Fees applicable
5. Timeline estimate
6. Tracking instructions
7. Renewal dates
8. Penalty information
9. RTO contact details

Include links to Parivahan portal."""

    def _get_rto_system_prompt(self) -> str:
        """Get RTO system prompt."""
        return """You are a vehicle RTO services assistant for Indian vehicle owners.
Provide accurate Parivahan portal guidance. Include fee structures.
Warn about penalties for expired documents."""

    def _format_rto_response(self, content: str, context: dict[str, Any]) -> str:
        """Format RTO response."""
        vehicle = context.get("vehicle_type", "vehicle")
        service = context.get("service_type", "service")
        state = context.get("state", "state")
        return f"""🚗 Vehicle RTO - {vehicle} ({service}) in {state}

{content}

🔗 Parivahan: https://parivahan.gov.in
📞 VAHAN/SARATHI: Available on portal
⚠️ Keep insurance and PUC valid"""


class TelecomAssistantAgent(BaseAgent):
    """Telecom services assistance agent."""

    role = "telecom-assistant"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.operators = [
            "Jio",
            "Airtel",
            "Vi (Vodafone Idea)",
            "BSNL",
            "JioFiber",
            "Airtel Xstream",
        ]
        self.trao_guidelines = [
            "Tariff transparency",
            "No hidden charges",
            "Porting within 7 days",
            "Bill dispute resolution",
            "Data speed disclosure",
        ]

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute telecom services assistance."""
        service_type = context.get("service_type", "prepaid")
        operator = context.get("current_operator", "unknown")
        state = context.get("state", "unknown")
        usage = context.get("monthly_usage", "not specified")

        prompt = self._build_telecom_prompt(service_type, operator, state, usage, context)

        # Use single mode for quick consumer guidance
        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt=self._get_telecom_system_prompt(),
        )

        return self._format_telecom_response(response.text, context)

    def _build_telecom_prompt(
        self,
        service_type: str,
        operator: str,
        state: str,
        usage: str,
        context: dict[str, Any],
    ) -> str:
        """Build telecom services prompt."""
        budget = context.get("budget_range", "not specified")
        complaint_type = context.get("complaint_type", "not applicable")

        return f"""Telecom Services Assistant

Service Type: {service_type}
Current Operator: {operator}
State: {state}
Monthly Usage: {usage}
Budget: {budget}
Complaint Type: {complaint_type}

Provide:
1. Plan recommendations (3-5 options)
2. Tariff comparison table
3. Bill analysis (if dispute)
4. Dispute resolution steps
5. Porting process (MNP)
6. Complaint filing process
7. Escalation path (operator→TRAI)
8. TRAI guidelines
9. Consumer rights

Include comparison tables."""

    def _get_telecom_system_prompt(self) -> str:
        """Get telecom system prompt."""
        return """You are a telecom services assistant for Indian consumers.
Provide unbiased plan comparisons. Include TRAI guidelines.
Guide on complaint escalation path."""

    def _format_telecom_response(self, content: str, context: dict[str, Any]) -> str:
        """Format telecom response."""
        service = context.get("service_type", "service")
        operator = context.get("current_operator", "operator")
        return f"""📱 Telecom Services - {service} ({operator})

{content}

🔗 TRAI: https://www.trai.gov.in
📞 Complaint Portal: https://complaints.trai.gov.in
⚠️ Porting time: 7 days (MNP)"""


class LegalAidAgent(BaseAgent):
    """Legal aid and consumer court assistance agent."""

    role = "legal-aid"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.court_levels = {
            "District": "District Consumer Forum / District Court",
            "State": "State Consumer Commission / High Court",
            "National": "NCDRC / Supreme Court",
        }
        self.legal_aid_types = [
            "Free legal aid (NLSA)",
            "Legal aid clinic",
            "Pro bono lawyer",
            "Court amicus curiae",
        ]

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute legal aid assistance."""
        matter_type = context.get("legal_matter_type", "consumer")
        state = context.get("state", "unknown")
        urgency = context.get("urgency", "normal")
        case_value = context.get("case_value", "not specified")

        prompt = self._build_legal_prompt(matter_type, state, urgency, case_value, context)

        # Use pipeline mode for structured legal guidance
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_legal_system_prompt(),
        )

        return self._format_legal_response(response.text, context)

    def _build_legal_prompt(
        self,
        matter_type: str,
        state: str,
        urgency: str,
        case_value: str,
        context: dict[str, Any],
    ) -> str:
        """Build legal aid prompt."""
        court_level = context.get("court_level", "district")

        return f"""Legal Aid Assistant

Legal Matter Type: {matter_type}
State: {state}
Urgency: {urgency}
Case Value: ₹{case_value}
Court Level: {court_level}

Provide:
1. Legal overview
2. Rights summary
3. Document checklist
4. Filing process
5. Court jurisdiction
6. Timeline estimate
7. Fee structure
8. Legal aid eligibility
9. Lawyer recommendations
10. Case tracking (e-Courts)

Include disclaimers and warnings."""

    def _get_legal_system_prompt(self) -> str:
        """Get legal system prompt."""
        return """You are a legal aid assistant for Indian citizens.
This is NOT legal advice. Always recommend consulting advocate.
Include legal aid eligibility and e-Courts tracking."""

    def _format_legal_response(self, content: str, context: dict[str, Any]) -> str:
        """Format legal response."""
        matter = context.get("legal_matter_type", "matter")
        state = context.get("state", "state")
        urgency = context.get("urgency", "urgency")
        return f"""⚖️ Legal Aid - {matter} ({state}, {urgency})

{content}

🔗 e-Courts: https://ecourts.gov.in
🔗 NCDRC: https://consumerforum.nic.in
📞 NLSA Helpline: 9988333333
⚠️ This is NOT legal advice. Consult advocate."""


class WaterUtilityAgent(BaseAgent):
    """Water and utility services assistance agent."""

    role = "water-utility"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.utility_types = {
            "water": "Municipal water supply",
            "sewerage": "Sewerage connection and maintenance",
            "electricity": "Power connection and billing",
            "gas": "PNG/CNG connection",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute water/utility services assistance."""
        utility_type = context.get("utility_type", "water")
        service_request = context.get("service_request", "new_connection")
        state = context.get("state", "unknown")
        city = context.get("city", "unknown")
        consumer_number = context.get("consumer_number", "not provided")

        prompt = self._build_utility_prompt(
            utility_type, service_request, state, city, consumer_number, context
        )

        # Use single mode for quick service guidance
        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt=self._get_utility_system_prompt(),
        )

        return self._format_utility_response(response.text, context)

    def _build_utility_prompt(
        self,
        utility_type: str,
        service_request: str,
        state: str,
        city: str,
        consumer_number: str,
        context: dict[str, Any],
    ) -> str:
        """Build utility services prompt."""
        connection_type = context.get("connection_type", "domestic")

        return f"""Water & Utility Services

Utility Type: {utility_type}
Service Request: {service_request}
State: {state}
City: {city}
Consumer Number: {consumer_number}
Connection Type: {connection_type}

Provide:
1. Service overview
2. Eligibility check
3. Document checklist
4. Application process
5. Fees applicable
6. Timeline estimate
7. Bill payment options
8. Complaint process
9. Escalation path
10. Contact information

Include links to utility portals."""

    def _get_utility_system_prompt(self) -> str:
        """Get utility system prompt."""
        return """You are a water and utility services assistant for Indian citizens.
Provide accurate municipal/utility guidance. Include complaint escalation.
Guide on CPGRAMS for unresolved issues."""

    def _format_utility_response(self, content: str, context: dict[str, Any]) -> str:
        """Format utility response."""
        utility = context.get("utility_type", "utility")
        city = context.get("city", "city")
        state = context.get("state", "state")
        return f"""💧 Utility Services - {utility} ({city}, {state})

{content}

🔗 Jal Shakti: https://jalshakti-dowr.gov.in
📞 CPGRAMS: https://pgportal.gov.in
⚠️ Escalate if unresolved > 7 days"""


def register_india_skills_batch4(
    registry: SkillRegistry, config: ArchonConfig, provider_router: ProviderRouter
) -> None:
    """Register India-specific skills batch 4 (skills 16-20)."""
    skills = [
        SkillDefinition(
            name="insurance-advisor",
            description="Advises Indian consumers on insurance selection, claims, and government schemes.",
            trigger_patterns=["insurance", "claim", "policy", "sum assured", "premium"],
            version="1.0.0",
            provider_preference="anthropic",
            cost_tier="standard",
            state="active",
        ),
        SkillDefinition(
            name="vehicle-rto",
            description="Guides vehicle owners through RTO services, documents, fees, and Parivahan flows.",
            trigger_patterns=["rto", "vehicle registration", "driving license", "parivahan", "puc"],
            version="1.0.0",
            provider_preference="openai",
            cost_tier="low",
            state="active",
        ),
        SkillDefinition(
            name="telecom-assistant",
            description="Helps with Indian telecom plans, billing disputes, MNP, and TRAI escalation paths.",
            trigger_patterns=["telecom", "mobile plan", "broadband", "porting", "trai complaint"],
            version="1.0.0",
            provider_preference="openai",
            cost_tier="low",
            state="active",
        ),
        SkillDefinition(
            name="legal-aid",
            description="Provides structured legal-aid guidance, filing steps, and e-Courts navigation for India.",
            trigger_patterns=["legal aid", "consumer court", "case filing", "ecourts", "lawyer"],
            version="1.0.0",
            provider_preference="anthropic",
            cost_tier="standard",
            state="active",
        ),
        SkillDefinition(
            name="water-utility",
            description="Assists with water and utility connections, complaints, billing, and municipal escalation.",
            trigger_patterns=[
                "water bill",
                "utility complaint",
                "new connection",
                "sewerage",
                "electricity bill",
            ],
            version="1.0.0",
            provider_preference="openai",
            cost_tier="low",
            state="active",
        ),
    ]

    for skill in skills:
        registry.register(skill)
