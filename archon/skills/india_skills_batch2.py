"""India-specific skill implementations for ARCHON - 16 missing skills."""

from __future__ import annotations
from typing import Any
from archon.agents.base_agent import BaseAgent
from archon.config import ArchonConfig
from archon.providers import ProviderRouter
from archon.skills.skill_registry import SkillDefinition, SkillRegistry


class CustomsImportAgent(BaseAgent):
    """Customs and import compliance assistance agent."""

    role = "customs-import"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        product_category = context.get("product_category", "general")
        origin_country = context.get("origin_country", "unknown")
        import_value = context.get("import_value", "not specified")
        port = context.get("port_of_import", "not specified")
        iec_code = context.get("iec_code", "not available")

        prompt = f"""Customs Import Assistant
Product: {product_category} | Origin: {origin_country} | Value: ₹{import_value}
Port: {port} | IEC: {iec_code}

Provide: 1. HS code classification 2. Duty calculation (BCD, IGST, Cess)
3. FTA benefits 4. Document checklist 5. Import policy status
6. DGFT compliance 7. Clearance process 8. Timeline & costs"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a customs import compliance assistant for Indian importers. Provide accurate HS code classification and duty calculations with DGFT/CBIC guidelines.",
        )
        return f"""📦 Customs Import - {product_category} from {origin_country}

{response.text}

🔗 ICEGate: https://www.icegate.gov.in | DGFT: https://www.dgft.gov.in"""


class ExportComplianceAgent(BaseAgent):
    """Export compliance and documentation assistance agent."""

    role = "export-compliance"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        product_type = context.get("product_type", "general")
        destination = context.get("destination_country", "unknown")
        export_value = context.get("export_value", "not specified")
        state = context.get("state", "unknown")
        iec_code = context.get("iec_code", "not available")

        prompt = f"""Export Compliance Assistant
Product: {product_type} | Destination: {destination} | Value: ₹{export_value}
State: {state} | IEC: {iec_code}

Provide: 1. Export policy status 2. HS code & duties 3. Document checklist
4. Incentive schemes (RoDTEP, EPCG) 5. FTA benefits 6. Quality control
7. Customs clearance 8. Bank realization 9. GST refund (LUT vs IGST)"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are an export compliance assistant for Indian exporters. Provide accurate export incentive guidance with DGFT/CBIC guidelines.",
        )
        return f"""🚢 Export Compliance - {product_type} to {destination}

{response.text}

🔗 DGFT: https://www.dgft.gov.in | ICEGate: https://www.icegate.gov.in"""


class FSSAIComplianceAgent(BaseAgent):
    """FSSAI food safety compliance assistance agent."""

    role = "fssai-compliance"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.license_types = {
            "basic": "< 12 lakh",
            "state": "12 lakh - 20 crore",
            "central": "> 20 crore",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        business_type = context.get("business_type", "manufacturer")
        food_category = context.get("food_category", "general")
        turnover = context.get("annual_turnover", "not specified")
        state = context.get("state", "unknown")

        prompt = f"""FSSAI Compliance Assistant
Business: {business_type} | Category: {food_category} | Turnover: ₹{turnover} | State: {state}

Provide: 1. License type (Basic/State/Central) 2. Document checklist
3. FoSCoS application process 4. Fees 5. Compliance (labeling, testing)
6. Food safety standards 7. Renewal process 8. Penalties 9. Inspection guidelines"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are an FSSAI compliance assistant for Indian food businesses. Provide accurate license guidance based on turnover with FoSCoS portal guidance.",
        )
        return f"""🍽️ FSSAI - {business_type} ({food_category})

{response.text}

🔗 FoSCoS: https://foscos.fssai.gov.in | FSSAI: https://www.fssai.gov.in"""


class GovtFormAssistantAgent(BaseAgent):
    """Government form filling assistance agent."""

    role = "govt-form-assistant"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.form_categories = {
            "income_tax": "ITR",
            "passport": "Passport",
            "pan": "PAN",
            "aadhaar": "Aadhaar",
            "driving_license": "DL",
            "voter_id": "Voter ID",
            "pension": "Pension",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        form_type = context.get("form_type", "general")
        state = context.get("state", "unknown")
        applicant_type = context.get("applicant_type", "individual")
        urgency = context.get("urgency", "normal")

        prompt = f"""Government Form Assistant
Form: {form_type} | State: {state} | Applicant: {applicant_type} | Urgency: {urgency}

Provide: 1. Eligibility criteria 2. Document checklist 3. Online application process
4. Fees applicable 5. Timeline estimate 6. Tracking instructions
7. Common errors to avoid 8. Grievance redressal 9. Related schemes"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a government form assistant for Indian citizens. Provide accurate form filling guidance with official portal links and document checklists.",
        )
        return f"""📋 Form Assistant - {form_type} ({state})

{response.text}

🔗 Portal: Check respective government website | 📞 UMANG App available"""


class GSTComplianceAgent(BaseAgent):
    """GST compliance and filing assistance agent."""

    role = "gst-compliance"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.return_types = {
            "GSTR-1": "Outward supplies",
            "GSTR-3B": "Summary return",
            "GSTR-9": "Annual return",
            "GSTR-4": "Composition scheme",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        gstin = context.get("gstin", "not provided")
        business_type = context.get("business_type", "regular")
        return_type = context.get("return_type", "GSTR-3B")
        tax_period = context.get("tax_period", "current")
        turnover = context.get("turnover", "not specified")

        prompt = f"""GST Compliance Assistant
GSTIN: {gstin} | Business: {business_type} | Return: {return_type}
Period: {tax_period} | Turnover: {turnover}

Provide: 1. Eligibility check 2. Form selection 3. Calculation worksheet
4. Document checklist 5. Filing steps 6. Due dates 7. Penalty info
8. ITC reconciliation 9. HSN classification 10. Place of supply rules"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a GST compliance assistant for Indian businesses. Provide accurate return filing guidance with calculation worksheets and CBIC guidelines.",
        )
        return f"""📊 GST Compliance - {return_type} ({business_type})

{response.text}

🔗 GST Portal: https://www.gst.gov.in | 📞 Helpline: 1800-103-4533"""


class HealthcareTriageAgent(BaseAgent):
    """Healthcare triage and facility guidance agent."""

    role = "healthcare-triage"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.triage_levels = {
            "emergency": "Immediate care needed",
            "urgent": "Within 24 hours",
            "routine": "Schedule appointment",
            "preventive": "Health checkup",
        }
        self.facility_types = {
            "PHC": "Primary Health Centre",
            "CHC": "Community Health Centre",
            "DH": "District Hospital",
            "AIIMS": "Tertiary care",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        symptoms = context.get("symptoms", "not specified")
        duration = context.get("duration_days", "unknown")
        patient_age = context.get("patient_age", "not provided")
        location = context.get("location", "unknown")
        existing_conditions = context.get("existing_conditions", "none")

        prompt = f"""Healthcare Triage Assistant
Symptoms: {symptoms} | Duration: {duration} days | Age: {patient_age}
Location: {location} | Existing conditions: {existing_conditions}

Provide: 1. Triage level (emergency/urgent/routine) 2. Facility recommendation
3. Immediate actions 4. Ayushman Bharat eligibility 5. Warning signs
6. Specialist referral if needed 7. Telemedicine options 8. Medicine guidance"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a healthcare triage assistant for Indian patients. Provide symptom assessment and facility recommendations. NOT a diagnosis - always recommend consulting a doctor.",
        )
        return f"""🏥 Healthcare Triage - {location}

{response.text}

🚨 Emergency: Call 108 | 🔗 Ayushman Bharat: https://pmjay.gov.in"""


class HRRecruitmentAgent(BaseAgent):
    """HR recruitment and hiring assistance agent."""

    role = "hr-recruitment"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.hiring_types = {
            "campus": "Campus recruitment",
            "lateral": "Lateral hiring",
            "bulk": "Bulk hiring",
            "contract": "Contractual staffing",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        company_size = context.get("company_size", "not specified")
        hiring_type = context.get("hiring_type", "regular")
        role_category = context.get("role_category", "general")
        location = context.get("location", "pan-India")
        budget = context.get("budget_range", "not specified")

        prompt = f"""HR Recruitment Assistant
Company Size: {company_size} | Hiring Type: {hiring_type} | Role: {role_category}
Location: {location} | Budget: {budget}

Provide: 1. Sourcing strategy 2. Job description template 3. Screening criteria
4. Interview process 5. Assessment tools 6. Offer letter template
7. Compliance (PF, ESIC, Professional Tax) 8. Onboarding checklist
9. Background verification process 10. Retention strategies"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are an HR recruitment assistant for Indian employers. Provide comprehensive hiring guidance with labor law compliance and best practices.",
        )
        return f"""💼 HR Recruitment - {role_category} ({location})

{response.text}

🔗 Naukri/LinkedIn | 📋 Labor Law Compliance Required"""


class KisanAdvisoryAgent(BaseAgent):
    """Agriculture advisory for farmers agent."""

    role = "kisan-advisory"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.crop_seasons = {
            "kharif": "June-October",
            "rabi": "October-March",
            "zaid": "March-June",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        region = context.get("region", "not specified")
        season = context.get("season", "current")
        soil_type = context.get("soil_type", "unknown")
        land_size = context.get("land_size_acres", "not specified")
        language = context.get("language", "english")

        prompt = f"""Kisan Advisory Assistant
Region: {region} | Season: {season} | Soil: {soil_type} | Land: {land_size} acres
Language: {language}

Provide: 1. Crop recommendations 2. Weather advisory 3. Mandi prices
4. Soil health guidance 5. Fertilizer recommendations 6. Irrigation schedule
7. Pest management 8. Government schemes (PM-KISAN, KCC) 9. Insurance options
10. Market linkage advice"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are an agriculture advisory assistant for Indian farmers. Provide crop recommendations, weather guidance, and mandi price information in regional languages.",
        )
        return f"""🌾 Kisan Advisory - {region} ({season})

{response.text}

🔗 e-NAM: https://enam.gov.in | 📞 Kisan Call Centre: 1800-180-1551"""


class MSMELoanAssistantAgent(BaseAgent):
    """MSME loan processing assistance agent."""

    role = "msme-loan-assistant"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.loan_schemes = {
            "MUDRA": "Micro units",
            "CGTMSE": "Credit guarantee",
            "PMEGP": "Employment generation",
            "UDYAM": "MSME registration",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        business_type = context.get("business_type", "not specified")
        loan_amount = context.get("loan_amount_requested", "not specified")
        state = context.get("state", "unknown")
        udyam_reg = context.get("udyam_registration", "not available")
        turnover = context.get("annual_turnover", "not specified")

        prompt = f"""MSME Loan Assistant
Business: {business_type} | Loan Amount: ₹{loan_amount} | State: {state}
Udyam: {udyam_reg} | Turnover: {turnover}

Provide: 1. Eligible schemes (MUDRA, CGTMSE, PMEGP) 2. Loan amount range
3. Interest rate range 4. Document checklist 5. Lender recommendations
6. Subsidy details 7. Application timeline 8. Udyam registration process
9. GST compliance 10. Repayment terms"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are an MSME loan assistant for Indian businesses. Provide accurate loan scheme guidance with eligibility, documentation, and lender matching.",
        )
        return f"""💰 MSME Loan - {business_type} ({state})

{response.text}

🔗 Udyam: https://udyamregistration.gov.in | MUDRA: https://www.mudra.org.in"""


class ONDCSellerAssistantAgent(BaseAgent):
    """ONDC seller onboarding and operations agent."""

    role = "ondc-seller-assistant"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.seller_types = {
            "retail": "Retail products",
            "F&B": "Food & Beverage",
            "services": "Services",
            "digital": "Digital products",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        business_type = context.get("business_type", "retail")
        category = context.get("product_category", "general")
        location = context.get("location", "not specified")
        gstin = context.get("gstin", "not available")
        platform = context.get("current_platform", "none")

        prompt = f"""ONDC Seller Assistant
Business: {business_type} | Category: {category} | Location: {location}
GST: {gstin} | Current Platform: {platform}

Provide: 1. ONDC overview 2. Eligibility check 3. Onboarding process
4. Seller app selection 5. Catalog creation 6. Order management
7. Logistics integration 8. Payment settlement 9. Customer support
10. Compliance requirements"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are an ONDC seller assistant for Indian merchants. Provide onboarding guidance, catalog setup, and operations support for ONDC network.",
        )
        return f"""🛒 ONDC Seller - {business_type} ({category})

{response.text}

🔗 ONDC: https://www.ondc.org | 📋 Seller App Partners Available"""


class PropertyVerificationAgent(BaseAgent):
    """Property verification and due diligence agent."""

    role = "property-verification"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.property_types = {
            "residential": "Residential property",
            "commercial": "Commercial",
            "agricultural": "Agricultural land",
            "plot": "Open plot",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        property_type = context.get("property_type", "residential")
        state = context.get("state", "unknown")
        city = context.get("city", "not specified")
        transaction_type = context.get("transaction_type", "purchase")
        budget = context.get("budget_range", "not specified")

        prompt = f"""Property Verification Assistant
Type: {property_type} | State: {state} | City: {city}
Transaction: {transaction_type} | Budget: {budget}

Provide: 1. Title verification process 2. Document checklist (Sale deed, EC, Khata)
3. Encumbrance certificate check 4. Property tax verification 5. RERA registration
6. Approval status (BDA, BDAQ, local body) 7. Due diligence steps
8. Legal opinion recommendation 9. Registration process 10. Stamp duty calculation"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a property verification assistant for Indian real estate. Provide due diligence guidance with document verification and legal compliance.",
        )
        return f"""🏠 Property Verification - {property_type} ({city})

{response.text}

🔗 RERA: Check state RERA portal | 📋 Consult property lawyer"""


class ScholarshipApplicationAgent(BaseAgent):
    """Scholarship application assistance agent."""

    role = "scholarship-application"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.scholarship_categories = {
            "merit": "Merit-based",
            "means": "Means-based",
            "category": "SC/ST/OBC",
            "minority": "Minority",
            "disabled": "Divyang",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        student_category = context.get("student_category", "general")
        education_level = context.get("education_level", "not specified")
        state = context.get("state", "unknown")
        family_income = context.get("family_income", "not specified")
        academic_performance = context.get("academic_performance", "not specified")

        prompt = f"""Scholarship Application Assistant
Category: {student_category} | Education: {education_level} | State: {state}
Income: {family_income} | Performance: {academic_performance}

Provide: 1. Eligible scholarships 2. Eligibility criteria 3. Document checklist
4. Application process (National/State portals) 5. Deadlines 6. Selection criteria
7. Renewal requirements 8. Disbursement process 9. Grievance redressal
10. Additional schemes (PFS, PMSSS, etc.)"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a scholarship application assistant for Indian students. Provide scholarship matching, eligibility guidance, and application support.",
        )
        return f"""🎓 Scholarship - {student_category} ({education_level})

{response.text}

🔗 National Scholarship Portal: https://scholarships.gov.in"""


class SolarAdoptionAgent(BaseAgent):
    """Solar adoption and subsidy assistance agent."""

    role = "solar-adoption"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.solar_types = {
            "rooftop": "Rooftop solar",
            "pump": "Solar pump",
            "street": "Street lighting",
            "commercial": "Commercial solar",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        solar_type = context.get("solar_type", "rooftop")
        state = context.get("state", "unknown")
        capacity_needed = context.get("capacity_needed", "not specified")
        property_type = context.get("property_type", "residential")
        budget = context.get("budget_range", "not specified")

        prompt = f"""Solar Adoption Assistant
Type: {solar_type} | State: {state} | Capacity: {capacity_needed}
Property: {property_type} | Budget: {budget}

Provide: 1. System size recommendation 2. Subsidy eligibility (PM Surya Ghar)
3. Cost estimate 4. Vendor selection 5. Installation process
6. Net metering process 7. ROI calculation 8. Maintenance requirements
9. State DISCOM guidelines 10. Financing options"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a solar adoption assistant for Indian consumers. Provide subsidy guidance, vendor selection, and installation support for solar systems.",
        )
        return f"""☀️ Solar Adoption - {solar_type} ({state})

{response.text}

🔗 PM Surya Ghar: https://pmsuryaghar.gov.in | 📞 State DISCOM"""


class StartupIndiaAgent(BaseAgent):
    """Startup India registration and benefits agent."""

    role = "startup-india"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.startup_types = {
            "tech": "Technology startup",
            "manufacturing": "Manufacturing",
            "services": "Services",
            "social": "Social enterprise",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        business_type = context.get("business_type", "tech")
        incorporation_date = context.get("incorporation_date", "not specified")
        state = context.get("state", "unknown")
        turnover = context.get("turnover", "not specified")
        sector = context.get("sector", "not specified")

        prompt = f"""Startup India Assistant
Type: {business_type} | Incorporated: {incorporation_date} | State: {state}
Turnover: {turnover} | Sector: {sector}

Provide: 1. DPIIT eligibility check 2. Registration steps 3. Document checklist
4. Tax benefits (80IAC) 5. IPR support 6. Funding options
7. Incubator recommendations 8. Compliance requirements 9. Timeline estimate
10. Tonnage limit verification (100Cr)"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a Startup India assistant for Indian entrepreneurs. Provide DPIIT recognition guidance, tax benefit information, and funding support.",
        )
        return f"""🚀 Startup India - {business_type} ({state})

{response.text}

🔗 Startup India: https://www.startupindia.gov.in | DPIIT Registration"""


class UPIFraudDetectionAgent(BaseAgent):
    """UPI fraud detection and prevention agent."""

    role = "upi-fraud-detection"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.fraud_types = {
            "phishing": "Phishing scams",
            "unauthorized": "Unauthorized transactions",
            "refund": "Refund scams",
            "merchant": "Fake merchant",
            "identity": "Identity theft",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        transaction_count = context.get("transaction_count", "not specified")
        amount_range = context.get("amount_range", "not specified")
        time_period = context.get("time_period", "not specified")
        merchant_vpa = context.get("merchant_vpa", "not available")
        bank_name = context.get("bank_name", "unknown")

        prompt = f"""UPI Fraud Detection Assistant
Transactions: {transaction_count} | Amount: ₹{amount_range} | Period: {time_period}
Merchant VPA: {merchant_vpa} | Bank: {bank_name}

Provide: 1. Fraud risk score 2. Risk indicators 3. Merchant verification status
4. Immediate actions 5. Reporting steps 6. Prevention tips
7. Bank contact 8. Cybercrime portal 9. Chargeback process 10. Legal recourse"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a UPI fraud detection assistant for Indian users. Analyze transaction patterns for fraud indicators and provide reporting guidance.",
        )
        return f"""💳 UPI Fraud Detection - Risk Analysis

{response.text}

🚨 Report: 1930 (Cybercrime) | 🔗 NPCI: https://www.npci.in"""


class ExplainSimplyTheoremAgent(BaseAgent):
    """Simple theorem/concept explanation agent."""

    role = "explain-simply-theorem"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.subjects = {
            "math": "Mathematics",
            "physics": "Physics",
            "cs": "Computer Science",
            "economics": "Economics",
            "biology": "Biology",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        theorem = context.get("theorem", "not specified")
        subject = context.get("subject", "general")
        level = context.get("level", "beginner")
        language = context.get("language", "english")

        prompt = f"""Simple Theorem Explanation
Theorem: {theorem} | Subject: {subject} | Level: {level} | Language: {language}

Provide: 1. Simple definition 2. Real-world example 3. Visual analogy
4. Step-by-step breakdown 5. Common misconceptions 6. Applications
7. Related concepts 8. Practice problems 9. Memory tricks 10. Further reading"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are an educational assistant that explains theorems and concepts simply. Use analogies, examples, and clear language suitable for the specified level.",
        )
        return f"""📚 Explained: {theorem} ({subject})

{response.text}

💡 Practice makes perfect! | 🔗 Khan Academy / NPTEL"""


def register_india_skills_batch2(
    registry: SkillRegistry, config: ArchonConfig, provider_router: ProviderRouter
) -> None:
    """Register India-specific skills batch 2 (16 missing skills)."""
    skills = [
        SkillDefinition(
            name="customs-import",
            version="1.0.0",
            provider_preference="anthropic",
            cost_tier="standard",
            state="active",
        ),
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
            provider_preference="openai",
            cost_tier="standard",
            state="active",
        ),
        SkillDefinition(
            name="govt-form-assistant",
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
            name="healthcare-triage",
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
            name="kisan-advisory",
            version="1.0.0",
            provider_preference="openai",
            cost_tier="low",
            state="active",
        ),
        SkillDefinition(
            name="msme-loan-assistant",
            version="1.0.0",
            provider_preference="openai",
            cost_tier="standard",
            state="active",
        ),
        SkillDefinition(
            name="ondc-seller-assistant",
            version="1.0.0",
            provider_preference="openai",
            cost_tier="low",
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
            name="scholarship-application",
            version="1.0.0",
            provider_preference="openai",
            cost_tier="low",
            state="active",
        ),
        SkillDefinition(
            name="solar-adoption",
            version="1.0.0",
            provider_preference="openai",
            cost_tier="low",
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
            name="upi-fraud-detection",
            version="1.0.0",
            provider_preference="anthropic",
            cost_tier="standard",
            state="active",
        ),
        SkillDefinition(
            name="explain-simply-theorem",
            version="1.0.0",
            provider_preference="openai",
            cost_tier="low",
            state="active",
        ),
    ]

    for skill in skills:
        registry.register(skill)
