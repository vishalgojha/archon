"""India-specific skill implementations for ARCHON - Skills 11-15."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import BaseAgent
from archon.config import ArchonConfig
from archon.core.types import TaskMode
from archon.providers import ProviderRouter
from archon.skills.skill_registry import SkillDefinition, SkillRegistry


class ExportComplianceAgent(BaseAgent):
    """Export compliance and documentation agent."""

    role = "export-compliance"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.export_schemes = [
            "RoDTEP (Remission of Duties and Taxes on Exported Products)",
            "EPCG (Export Promotion Capital Goods)",
            "Advance Authorization",
            "Drawback Scheme",
            "MEIS (if applicable)",
        ]

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute export compliance assistance."""
        product = context.get("product_type", "unknown")
        destination = context.get("destination_country", "unknown")
        value = context.get("export_value", 0)
        iec = context.get("iec_code", "not provided")
        
        prompt = self._build_export_prompt(product, destination, value, iec, context)
        
        # Use debate mode for multi-regulation analysis
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_export_system_prompt(),
        )
        
        return self._format_export_response(response.content, context)

    def _build_export_prompt(
        self,
        product: str,
        destination: str,
        value: float,
        iec: str,
        context: dict[str, Any],
    ) -> str:
        """Build export compliance prompt."""
        state = context.get("state", "unknown")
        incoterms = context.get("incoterms", "FOB")
        
        return f"""Export Compliance Assistant

Product: {product}
Destination: {destination}
Export Value: ₹{value:,}
IEC Code: {iec}
State: {state}
Incoterms: {incoterms}

Provide:
1. Export eligibility check
2. Document checklist (IEC, shipping bill, COO)
3. HS code classification
4. Customs procedures
5. Export incentive schemes (RoDTEP, EPCG, drawback)
6. Destination country requirements
7. Timeline estimate
8. Cost breakdown (customs, freight, documentation)

Include tables for duty calculations."""

    def _get_export_system_prompt(self) -> str:
        """Get export system prompt."""
        return """You are an export compliance assistant for Indian businesses.
Provide accurate DGFT and customs guidance. Recommend customs broker for complex shipments.
Include incentive scheme details."""

    def _format_export_response(self, content: str, context: dict[str, Any]) -> str:
        """Format export response."""
        product = context.get("product_type", "product")
        destination = context.get("destination_country", "destination")
        return f"""📦 Export Compliance - {product} to {destination}

{content}

🔗 DGFT: https://dgft.gov.in
🔗 Icegate: https://icegate.gov.in
⚠️ Consult customs broker for shipment > ₹50L"""


class FSSAIComplianceAgent(BaseAgent):
    """FSSAI food safety compliance agent."""

    role = "fssai-compliance"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.license_types = {
            "Basic": "Turnover < 12L, small manufacturers",
            "State": "Turnover 12L-20Cr, medium businesses",
            "Central": "Turnover > 20Cr, large manufacturers, importers",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute FSSAI compliance assistance."""
        business_type = context.get("business_type", "unknown")
        food_category = context.get("food_category", "general")
        state = context.get("state", "unknown")
        turnover = context.get("annual_turnover", "not specified")
        
        prompt = self._build_fssai_prompt(business_type, food_category, state, turnover, context)
        
        # Use pipeline mode for structured compliance
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_fssai_system_prompt(),
        )
        
        return self._format_fssai_response(response.content, context)

    def _build_fssai_prompt(
        self,
        business_type: str,
        food_category: str,
        state: str,
        turnover: str,
        context: dict[str, Any],
    ) -> str:
        """Build FSSAI compliance prompt."""
        product_count = context.get("product_count", "not specified")
        
        return f"""FSSAI Compliance Assistant

Business Type: {business_type}
Food Category: {food_category}
State: {state}
Annual Turnover: {turnover}
Product Count: {product_count}

Provide:
1. License type required (Basic/State/Central)
2. Application process (FoSCoS portal)
3. Document checklist
4. Hygiene standards (FSSAI guidelines)
5. Labeling requirements (ingredients, expiry, FSSAI logo)
6. Testing requirements (NABL labs)
7. Renewal process
8. Penalty information
9. Recall procedures

Include checklists and templates."""

    def _get_fssai_system_prompt(self) -> str:
        """Get FSSAI system prompt."""
        return """You are an FSSAI compliance assistant for Indian food businesses.
Provide accurate licensing guidance. Include food safety standards.
Recommend food safety officer consultation for complex cases."""

    def _format_fssai_response(self, content: str, context: dict[str, Any]) -> str:
        """Format FSSAI response."""
        business = context.get("business_type", "business")
        state = context.get("state", "state")
        return f"""🍽️ FSSAI Compliance - {business} ({state})

{content}

🔗 FoSCoS Portal: https://foscos.fssai.gov.in
📞 FSSAI Helpline: 1800-112-100
⚠️ Verify license requirements on FSSAI portal"""


class StartupIndiaAgent(BaseAgent):
    """Startup India registration and benefits agent."""

    role = "startup-india"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.benefits = [
            "Tax holiday (80IAC deduction)",
            "Angel tax exemption",
            "IPR fast-track filing",
            "Government tenders exemption",
            "Funding support (FOne)",
            "Incubator support",
            "Compliance exemptions",
        ]

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute Startup India assistance."""
        business_type = context.get("business_type", "tech")
        incorporation = context.get("incorporation_date", "unknown")
        state = context.get("state", "unknown")
        turnover = context.get("turnover", "not specified")
        
        prompt = self._build_startup_prompt(business_type, incorporation, state, turnover, context)
        
        # Use pipeline mode for multi-stage guidance
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_startup_system_prompt(),
        )
        
        return self._format_startup_response(response.content, context)

    def _build_startup_prompt(
        self,
        business_type: str,
        incorporation: str,
        state: str,
        turnover: str,
        context: dict[str, Any],
    ) -> str:
        """Build Startup India prompt."""
        sector = context.get("sector", "technology")
        team_size = context.get("team_size", "not specified")
        
        return f"""Startup India Assistant

Business Type: {business_type}
Incorporation Date: {incorporation}
State: {state}
Turnover: {turnover}
Sector: {sector}
Team Size: {team_size}

Provide:
1. Eligibility check (10 years, 100Cr turnover, innovative)
2. DPIIT registration steps
3. Document checklist
4. Tax benefits (80IAC, angel tax)
5. IPR support (patent filing)
6. Funding options (VC, angel, government)
7. Incubator recommendations
8. Compliance requirements
9. Timeline estimate

Include links to Startup India portal."""

    def _get_startup_system_prompt(self) -> str:
        """Get Startup India system prompt."""
        return """You are a Startup India assistant for Indian entrepreneurs.
Provide accurate DPIIT recognition guidance. Include tax and funding benefits.
Recommend CA consultation for tax planning."""

    def _format_startup_response(self, content: str, context: dict[str, Any]) -> str:
        """Format Startup India response."""
        sector = context.get("sector", "sector")
        state = context.get("state", "state")
        return f"""🚀 Startup India - {sector} ({state})

{content}

🔗 Startup India: https://startupindia.gov.in
📞 DPIIT Helpline: 1800-111-111
⚠️ Turnover limit: ₹100Cr for 10 years from incorporation"""


class SolarAdoptionAgent(BaseAgent):
    """Solar energy adoption and subsidy agent."""

    role = "solar-adoption"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.subsidy_schemes = {
            "Residential": "Rooftop Solar Subsidy (40% for <3kW, 20% for 3-10kW)",
            "Commercial": "PM-KUSUM Component C",
            "Agricultural": "PM-KUSUM Component B (solar pumps)",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute solar adoption assistance."""
        install_type = context.get("installation_type", "residential")
        state = context.get("state", "unknown")
        roof_area = context.get("roof_area_sqft", 0)
        consumption = context.get("monthly_consumption_units", "not specified")
        
        prompt = self._build_solar_prompt(install_type, state, roof_area, consumption, context)
        
        # Use pipeline mode for technical→financial→installation
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_solar_system_prompt(),
        )
        
        return self._format_solar_response(response.content, context)

    def _build_solar_prompt(
        self,
        install_type: str,
        state: str,
        roof_area: float,
        consumption: str,
        context: dict[str, Any],
    ) -> str:
        """Build solar adoption prompt."""
        budget = context.get("budget_range", "not specified")
        
        return f"""Solar Adoption Assistant

Installation Type: {install_type}
State: {state}
Roof Area: {roof_area} sqft
Monthly Consumption: {consumption} units
Budget: {budget}

Provide:
1. System size recommendation (kW)
2. Subsidy eligibility (state scheme)
3. Cost breakdown (panels, inverter, installation)
4. ROI analysis (payback period)
5. Installation steps
6. DISCOM net-metering procedures
7. Vendor recommendations
8. Loan options
9. Maintenance guide

Include calculations and tables."""

    def _get_solar_system_prompt(self) -> str:
        """Get solar system prompt."""
        return """You are a solar energy adoption assistant for Indian users.
Provide accurate system sizing and subsidy guidance. Include ROI calculations.
Recommend site survey for large installations."""

    def _format_solar_response(self, content: str, context: dict[str, Any]) -> str:
        """Format solar response."""
        install_type = context.get("installation_type", "installation")
        state = context.get("state", "state")
        return f"""☀️ Solar Adoption - {install_type} ({state})

{content}

🔗 MNRE: https://mnre.gov.in
🔗 State DISCOM: Check your DISCOM portal
⚠️ Site survey recommended for systems > 10kW"""


class CustomsImportAgent(BaseAgent):
    """Customs import clearance and duty agent."""

    role = "customs-import"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.duty_components = [
            "Basic Customs Duty (BCD)",
            "Social Welfare Surcharge (SWS)",
            "IGST",
            "Cess (if applicable)",
        ]

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute customs import assistance."""
        product = context.get("product_type", "unknown")
        origin = context.get("origin_country", "unknown")
        value = context.get("import_value", 0)
        port = context.get("port_of_entry", "unknown")
        iec = context.get("iec_code", "not provided")
        
        prompt = self._build_import_prompt(product, origin, value, port, iec, context)
        
        # Use debate mode for multi-regulation analysis
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_import_system_prompt(),
        )
        
        return self._format_import_response(response.content, context)

    def _build_import_prompt(
        self,
        product: str,
        origin: str,
        value: float,
        port: str,
        iec: str,
        context: dict[str, Any],
    ) -> str:
        """Build customs import prompt."""
        state = context.get("state", "unknown")
        incoterms = context.get("incoterms", "CIF")
        
        return f"""Customs Import Assistant

Product: {product}
Origin: {origin}
Import Value: ₹{value:,}
Port: {port}
IEC Code: {iec}
State: {state}
Incoterms: {incoterms}

Provide:
1. Import eligibility check
2. Document checklist (IEC, Bill of Entry, invoices)
3. HS code classification
4. Duty calculation (BCD, SWS, IGST, cess)
5. Restricted item check (DGFT ITC-HS)
6. Clearance procedures
7. Timeline estimate
8. Cost breakdown (duty, port charges, freight)
9. Port-specific requirements

Include tables for duty calculations."""

    def _get_import_system_prompt(self) -> str:
        """Get import system prompt."""
        return """You are a customs import assistant for Indian businesses.
Provide accurate customs duty guidance. Recommend customs broker for complex imports.
Include restricted item warnings."""

    def _format_import_response(self, content: str, context: dict[str, Any]) -> str:
        """Format import response."""
        product = context.get("product_type", "product")
        origin = context.get("origin_country", "origin")
        port = context.get("port_of_entry", "port")
        return f"""📦 Customs Import - {product} from {origin} ({port})

{content}

🔗 Icegate: https://icegate.gov.in
🔗 DGFT ITC-HS: https://dgft.gov.in
⚠️ Consult customs broker for shipment > ₹50L"""


def register_india_skills_batch3(registry: SkillRegistry, config: ArchonConfig, provider_router: ProviderRouter) -> None:
    """Register India-specific skills batch 3 (skills 11-15)."""
    skills = [
        SkillDefinition(
            name="export-compliance",
            version="1.0.0",
            provider_preference="anthropic",
            cost_tier="standard",
            state="active",
        ),
        SkillDefinition(
            name="fssai-compliance",
            version="1.0.0",
            provider_preference="anthropic",
            cost_tier="standard",
            state="active",
        ),
        SkillDefinition(
            name="startup-india",
            version="1.0.0",
            provider_preference="openai",
            cost_tier="low",
            state="active",
        ),
        SkillDefinition(
            name="solar-adoption",
            version="1.0.0",
            provider_preference="openai",
            cost_tier="standard",
            state="active",
        ),
        SkillDefinition(
            name="customs-import",
            version="1.0.0",
            provider_preference="anthropic",
            cost_tier="standard",
            state="active",
        ),
    ]
    
    for skill in skills:
        registry.register(skill)
