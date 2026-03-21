"""India-specific skill implementations for ARCHON - Next 5 skills."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import BaseAgent
from archon.config import ArchonConfig
from archon.core.types import TaskMode
from archon.providers import ProviderRouter
from archon.skills.skill_registry import SkillDefinition, SkillRegistry


class ONDCSellerAgent(BaseAgent):
    """ONDC seller onboarding and operations agent."""

    role = "ondc-seller-assistant"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.onboarding_steps = [
            "1. Udyam Registration (MSME)",
            "2. GST Registration",
            "3. Choose ONDC Seller App",
            "4. Complete KYC",
            "5. Product Catalog Upload",
            "6. Logistics Partner Selection",
            "7. Go Live",
        ]

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute ONDC seller assistance."""
        business_type = context.get("business_type", "kirana")
        state = context.get("state", "unknown")
        gst = context.get("gst_number", "not provided")
        
        prompt = self._build_onboarding_prompt(business_type, state, gst, context)
        
        # Use pipeline mode for structured onboarding
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_onboarding_system_prompt(),
        )
        
        return self._format_onboarding_response(response.content, context)

    def _build_onboarding_prompt(
        self,
        business_type: str,
        state: str,
        gst: str,
        context: dict[str, Any],
    ) -> str:
        """Build ONDC onboarding prompt."""
        category = context.get("product_category", "general")
        pin_code = context.get("pin_code", "unknown")
        
        return f"""ONDC Seller Assistant

Business Type: {business_type}
State: {state}
GST Number: {gst}
Product Category: {category}
Pin Code: {pin_code}

Provide:
1. ONDC onboarding steps
2. Document checklist (Udyam, GST, bank)
3. Seller app recommendations for {state}
4. Product listing optimization tips
5. Logistics partner options
6. Commission structure
7. Customer support templates
8. GST invoice generation guide

Include links to ONDC resources."""

    def _get_onboarding_system_prompt(self) -> str:
        """Get ONDC system prompt."""
        return """You are an ONDC seller assistant for Indian businesses.
Provide practical, actionable guidance. Link to official ONDC resources.
Help small sellers and kirana stores go digital."""

    def _format_onboarding_response(self, content: str, context: dict[str, Any]) -> str:
        """Format ONDC response."""
        business = context.get("business_type", "business")
        state = context.get("state", "state")
        return f"""🛒 ONDC Seller Assistant - {business} ({state})

{content}

🔗 ONDC Network: https://ondc.org
📞 Seller App Support: Check your chosen app
⚠️ Commission rates vary by platform"""


class GSTComplianceAgent(BaseAgent):
    """GST compliance and filing assistance agent."""

    role = "gst-compliance"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.return_types = {
            "GSTR-1": "Outward supplies (monthly/quarterly)",
            "GSTR-3B": "Summary return (monthly)",
            "GSTR-9": "Annual return",
            "GSTR-4": "Composition scheme annual",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute GST compliance assistance."""
        gstin = context.get("gstin", "not provided")
        return_type = context.get("return_type", "GSTR-3B")
        period = context.get("tax_period", "current")
        scheme = context.get("scheme_type", "regular")
        
        prompt = self._build_gst_prompt(gstin, return_type, period, scheme, context)
        
        # Use pipeline mode for structured compliance
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_gst_system_prompt(),
        )
        
        return self._format_gst_response(response.content, context)

    def _build_gst_prompt(
        self,
        gstin: str,
        return_type: str,
        period: str,
        scheme: str,
        context: dict[str, Any],
    ) -> str:
        """Build GST compliance prompt."""
        turnover = context.get("turnover", "not specified")
        sector = context.get("sector", "general")
        
        return f"""GST Compliance Assistant

GSTIN: {gstin}
Return Type: {return_type}
Tax Period: {period}
Scheme: {scheme}
Turnover: {turnover}
Sector: {sector}

Provide:
1. Eligibility check for {return_type}
2. Form selection guidance
3. Calculation worksheet (CGST, SGST, IGST)
4. Document checklist
5. Filing steps on GST portal
6. Due dates and penalties
7. ITC reconciliation guide
8. HSN classification tips

Include tables for calculations."""

    def _get_gst_system_prompt(self) -> str:
        """Get GST system prompt."""
        return """You are a GST compliance assistant for Indian businesses.
Provide accurate filing guidance. Always recommend CA consultation for complex cases.
Include penalty information for delays."""

    def _format_gst_response(self, content: str, context: dict[str, Any]) -> str:
        """Format GST response."""
        return_type = context.get("return_type", "return")
        period = context.get("tax_period", "period")
        return f"""📊 GST Compliance - {return_type} ({period})

{content}

🔗 GST Portal: https://www.gst.gov.in
📞 GST Helpdesk: 0124-4688999
⚠️ Consult CA for complex transactions"""


class PropertyVerificationAgent(BaseAgent):
    """Property verification and real estate assistance agent."""

    role = "property-verification"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.doc_checklist = [
            "Title Deed",
            "Encumbrance Certificate (13 years)",
            "Property Tax Receipts",
            "Approved Building Plan",
            "Occupancy Certificate",
            "RERA Registration",
            "Sale Agreement",
            "Mother Deed",
        ]

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute property verification assistance."""
        property_type = context.get("property_type", "residential")
        location = context.get("location", "unknown")
        transaction = context.get("transaction_type", "buy")
        value = context.get("property_value", "not specified")
        
        prompt = self._build_property_prompt(property_type, location, transaction, value, context)
        
        # Use debate mode for multi-source verification
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_property_system_prompt(),
        )
        
        return self._format_property_response(response.content, context)

    def _build_property_prompt(
        self,
        property_type: str,
        location: str,
        transaction: str,
        value: str,
        context: dict[str, Any],
    ) -> str:
        """Build property verification prompt."""
        state = context.get("state", "unknown")
        
        return f"""Property Verification Assistant

Property Type: {property_type}
Location: {location}
Transaction: {transaction}
Value: ₹{value}
State: {state}

Provide:
1. Title verification steps
2. RERA compliance check
3. Document checklist
4. Encumbrance certificate guide
5. Agreement template key clauses
6. Home loan comparison
7. Registration process
8. Stamp duty & registration fee
9. Property tax calculation
10. Red flags to watch

Include state-specific requirements."""

    def _get_property_system_prompt(self) -> str:
        """Get property system prompt."""
        return """You are a property verification assistant for Indian real estate.
Always recommend legal verification. Highlight red flags.
Include RERA and land record portal links."""

    def _format_property_response(self, content: str, context: dict[str, Any]) -> str:
        """Format property response."""
        location = context.get("location", "location")
        prop_type = context.get("property_type", "property")
        return f"""🏠 Property Verification - {prop_type} ({location})

{content}

🔗 RERA Portal: Check state RERA website
📞 Legal Consultation: Recommended before transaction
⚠️ Verify with registered lawyer"""


class HRRecruitmentAgent(BaseAgent):
    """HR recruitment and compliance assistance agent."""

    role = "hr-recruitment"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.salary_benchmarks = {
            "entry_level": "₹3-6 LPA",
            "mid_level": "₹6-15 LPA",
            "senior_level": "₹15-40 LPA",
            "leadership": "₹40L+ LPA",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute HR recruitment assistance."""
        job_role = context.get("job_role", "unknown")
        location = context.get("location", "pan-India")
        experience = context.get("experience_range", "0-2 years")
        industry = context.get("industry", "IT")
        
        prompt = self._build_hr_prompt(job_role, location, experience, industry, context)
        
        # Use pipeline mode for structured recruitment
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_hr_system_prompt(),
        )
        
        return self._format_hr_response(response.content, context)

    def _build_hr_prompt(
        self,
        job_role: str,
        location: str,
        experience: str,
        industry: str,
        context: dict[str, Any],
    ) -> str:
        """Build HR recruitment prompt."""
        salary_range = context.get("salary_range", "not specified")
        company_size = context.get("company_size", "SMB")
        
        return f"""HR Recruitment Assistant

Job Role: {job_role}
Location: {location}
Experience: {experience}
Industry: {industry}
Salary Range: {salary_range}
Company Size: {company_size}

Provide:
1. Candidate match scoring criteria
2. Education equivalence (Indian universities)
3. Experience validation tips
4. Salary benchmark for {location}
5. Notice period expectations
6. Compliance checklist (PF, ESI, labor laws)
7. Offer letter template
8. Background verification steps
9. Onboarding checklist

Include state-specific labor law compliance."""

    def _get_hr_system_prompt(self) -> str:
        """Get HR system prompt."""
        return """You are an HR recruitment assistant for Indian companies.
Provide fair, compliant hiring guidance. Include labor law compliance.
Recommend background verification for all hires."""

    def _format_hr_response(self, content: str, context: dict[str, Any]) -> str:
        """Format HR response."""
        role = context.get("job_role", "role")
        location = context.get("location", "location")
        return f"""💼 HR Recruitment - {role} ({location})

{content}

🔗 Job Portals: Naukri, LinkedIn, Indeed
📞 Labor Dept: Check state regulations
⚠️ Verify education and employment history"""


class UPIFraudDetectionAgent(BaseAgent):
    """UPI fraud detection and prevention agent."""

    role = "upi-fraud-detection"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.fraud_indicators = [
            "Multiple small transactions in short time",
            "New merchant with large amount",
            "Unusual time (late night) transactions",
            "Phishing link clicks",
            "OTP sharing requests",
            "Refund scams",
            "Fake customer care numbers",
        ]

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute UPI fraud detection assistance."""
        tx_count = context.get("transaction_count", 0)
        amount_range = context.get("amount_range", "unknown")
        period = context.get("time_period", "24 hours")
        merchant_vpa = context.get("merchant_vpa", "not provided")
        
        prompt = self._build_fraud_prompt(tx_count, amount_range, period, merchant_vpa, context)
        
        # Use debate mode for multi-perspective analysis
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_fraud_system_prompt(),
        )
        
        return self._format_fraud_response(response.content, context)

    def _build_fraud_prompt(
        self,
        tx_count: int,
        amount_range: str,
        period: str,
        merchant_vpa: str,
        context: dict[str, Any],
    ) -> str:
        """Build fraud detection prompt."""
        bank = context.get("bank_name", "unknown")
        tx_type = context.get("transaction_type", "P2M")
        
        return f"""UPI Fraud Detection Assistant

Transaction Count: {tx_count}
Amount Range: {amount_range}
Time Period: {period}
Merchant VPA: {merchant_vpa}
Bank: {bank}
Transaction Type: {tx_type}

Provide:
1. Fraud risk score (0-100)
2. Risk indicators detected
3. Merchant verification status
4. Immediate actions required
5. Reporting steps (bank, cybercrime)
6. Prevention tips
7. Bank fraud helpline
8. Cybercrime portal link

Be conservative in risk assessment."""

    def _get_fraud_system_prompt(self) -> str:
        """Get fraud detection system prompt."""
        return """You are a UPI fraud detection assistant for Indian users.
Prioritize user safety. When in doubt, recommend reporting to bank.
Include emergency contact numbers."""

    def _format_fraud_response(self, content: str, context: dict[str, Any]) -> str:
        """Format fraud response."""
        risk_level = "HIGH" if context.get("transaction_count", 0) > 10 else "MEDIUM"
        return f"""⚠️ UPI Fraud Alert - Risk Level: {risk_level}

{content}

🚨 Immediate Actions:
- Contact bank: {context.get('bank_name', 'your bank')}
- Cybercrime Portal: https://cybercrime.gov.in
- National Helpline: 1930

⚠️ Report immediately for unauthorized transactions"""


def register_india_skills_batch2(registry: SkillRegistry, config: ArchonConfig, provider_router: ProviderRouter) -> None:
    """Register India-specific skills batch 2 (skills 6-10)."""
    skills = [
        SkillDefinition(
            name="ondc-seller-assistant",
            version="1.0.0",
            provider_preference="openai",
            cost_tier="low",
            state="active",
        ),
        SkillDefinition(
            name="gst-compliance",
            version="1.0.0",
            provider_preference="anthropic",
            cost_tier="standard",
            state="active",
        ),
        SkillDefinition(
            name="property-verification",
            version="1.0.0",
            provider_preference="anthropic",
            cost_tier="standard",
            state="active",
        ),
        SkillDefinition(
            name="hr-recruitment",
            version="1.0.0",
            provider_preference="openai",
            cost_tier="standard",
            state="active",
        ),
        SkillDefinition(
            name="upi-fraud-detection",
            version="1.0.0",
            provider_preference="anthropic",
            cost_tier="standard",
            state="active",
        ),
    ]
    
    for skill in skills:
        registry.register(skill)
