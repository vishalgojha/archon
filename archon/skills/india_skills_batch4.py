"""India-specific skill implementations for ARCHON - Batch 4 (20+ skills)."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import BaseAgent
from archon.config import ArchonConfig
from archon.providers import ProviderRouter
from archon.skills.skill_registry import SkillDefinition, SkillRegistry


class DigilockerAgent(BaseAgent):
    """Digilocker document storage and verification agent."""

    role = "digilocker"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "document_fetch")
        document_type = context.get("document_type", "aadhaar")

        prompt = f"""Digilocker Assistant
Request: {request_type}
Document: {document_type}

Provide:
1. Digilocker registration process (mobile + Aadhaar)
2. Document fetch steps (PAN, Aadhaar, RC, marksheet)
3. Issuer search (CBSE, IRS, RTO, etc.)
4. Sharing documents with agencies
5. DigiDoc verification process
6. Document upload and storage
7. Linked issuer accounts
8. Offline access setup
9. Account recovery
10. Data privacy settings
11. mParivahan integration"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a Digilocker assistant. Provide accurate document fetching guidance with issuer links and verification steps.",
        )
        return f"""📱 Digilocker - {request_type}

{response.text}

🔗 Digilocker: https://digilocker.gov.in
🔗 mParivahan: https://parivahan.gov.in"""


class EShramAgent(BaseAgent):
    """e-Shram worker registration and social security agent."""

    role = "e-shram"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "registration")
        occupation = context.get("occupation", "not specified")
        state = context.get("state", "unknown")

        prompt = f"""e-Shram Worker Registration Assistant
Request: {request_type}
Occupation: {occupation}
State: {state}

Provide:
1. Eligibility check (unorganized sector)
2. Registration process (UAN card)
3. Required documents (Aadhaar, bank account)
4. Benefits (PMSBY, accident insurance)
5. e-Shram card download
6. Occupation code selection
7. Family member linking
8. Scheme eligibility check (PM-SYM, PM-SBY)
9. Skill India integration
10. Grievance redressal
11. State-specific benefits
12. NCS job portal linkage"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are an e-Shram assistant for unorganized workers. Provide accurate registration guidance with UAN card and social security benefits.",
        )
        return f"""👷 e-Shram - {request_type}

{response.text}

🔗 e-Shram: https://eshram.gov.in
📞 Helpline: 14434"""


class RationCardAgent(BaseAgent):
    """Ration card, PDS, and food security agent."""

    role = "ration-card"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "new_application")
        card_type = context.get("card_type", "APL")
        state = context.get("state", "unknown")
        family_size = context.get("family_size", "not specified")

        prompt = f"""Ration Card & PDS Assistant
Request: {request_type}
Card Type: {card_type} (BPL/APL/AAY)
State: {state}
Family Size: {family_size}

Provide:
1. Eligibility criteria (BPL/APL/AAY)
2. State-specific application process
3. Document checklist
4. Online/offline application
5. Fee structure
6. Status tracking
7. One Nation One Ration Card (ONORC)
8. Portability for migrants
9. Fair price shop locator
10. Monthly entitlements
11. Digital ration card
12. Grievance redressal"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a ration card and PDS assistant for Indian citizens. Provide accurate application guidance with state-specific portal links.",
        )
        return f"""🍚 Ration Card - {request_type}

{response.text}

🔗 NFSA: https://nfsa.gov.in
🔗 State Portals: Check respective state food website"""


class GasSubsidyAgent(BaseAgent):
    """PM Ujjwala Yojana and gas subsidy agent."""

    role = "gas-subsidy"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "subsidy_status")
        gas_provider = context.get("gas_provider", "not specified")
        state = context.get("state", "unknown")

        prompt = f"""Gas Subsidy & Ujjwala Yojana Assistant
Request: {request_type}
Provider: {gas_provider} (HP/BP/Indane)
State: {state}

Provide:
1. Subsidy status check (DBT to bank)
2. PM Ujjwala eligibility
3. New connection application
4. Document checklist (BPL certificate, Aadhaar)
5. Subsidy amount by state
6. Bank linking for DBT
7. Complaint (no subsidy received)
8. Portability between providers
9. Emergency refill process
10. Safety guidelines
11. Online booking (SMS/app)
12. Distributor locator"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a gas subsidy and Ujjwala Yojana assistant. Provide accurate subsidy guidance with DBT status and provider portal links.",
        )
        return f"""🔥 Gas Subsidy - {request_type}

{response.text}

🔗 PMUY: https://pmuy.gov.in
🔗 My LPG: https://mylpg.in
📞 Gas Helpline: 1800-233-3555"""


class UMANGAgent(BaseAgent):
    """UMANG app services and government scheme agent."""

    role = "umang"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        service_type = context.get("service_type", "general")
        department = context.get("department", "not specified")

        prompt = f"""UMANG Government Services Assistant
Service: {service_type}
Department: {department}

Provide:
1. UMANG registration process (mobile + Aadhaar)
2. Service categories (PF, pension, e-District, etc.)
3. Department-wise service list
4. Profile setup and e-KYC
5. Multi-language support (13 languages)
6. Service search and discovery
7. Application status tracking
8. Document upload process
9. Payment integration
10. Grievance filing
11. Nearby service center search
12. Notification settings"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a UMANG assistant for Indian citizens. Provide accurate app navigation and service discovery guidance.",
        )
        return f"""📱 UMANG - {service_type}

{response.text}

🔗 UMANG: https://www.umang.gov.in
📞 Helpline: 1800-115-565"""


class CEIRAgent(BaseAgent):
    """CEIR lost/stolen mobile tracking and blocking agent."""

    role = "ceir"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "lost_mobile")
        mobile_number = context.get("mobile_number", "not provided")
        state = context.get("state", "unknown")

        prompt = f"""CEIR Lost/Stolen Mobile Assistant
Request: {request_type}
Mobile: {mobile_number[:4]}XXXX
State: {state}

Provide:
1. Immediate actions (block SIM, change passwords)
2. FIR filing process (online/offline)
3. CEIR blocking request
4. Required documents (ID proof, bill, FIR copy)
5. IMEI number retrieval
6. Telecom operator blocking
7. Location tracking request
8. Unblocking process (if recovered)
9. Insurance claim process
10. Duplicate SIM request
11. Data protection steps
12. Cyber crime complaint"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a CEIR mobile blocking assistant. Provide accurate blocking guidance with CEIR portal and cyber crime steps.",
        )
        return f"""📱 CEIR - {request_type}

{response.text}

🔗 CEIR: https://www.ceir.gov.in
📞 Cyber Crime: 1930
🔗 Sanchar Saathi: https://sancharsaathi.gov.in"""


class NCSCareerAgent(BaseAgent):
    """National Career Service job search and career guidance agent."""

    role = "ncs-career"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "job_search")
        qualification = context.get("qualification", "not specified")
        location = context.get("location", "not specified")
        experience = context.get("experience", "fresher")

        prompt = f"""National Career Service Assistant
Request: {request_type}
Qualification: {qualification}
Location: {location}
Experience: {experience}

Provide:
1. NCS registration process
2. Profile creation tips
3. Job search strategies
4. Skill assessment tools
5. Career counseling options
6. Training program search
7. Employer matching
8. Resume builder
9. Interview preparation
10. Career fair calendar
11. Self-employment guidance
12. Government job alerts"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a National Career Service assistant for Indian job seekers. Provide accurate career guidance with NCS portal navigation.",
        )
        return f"""💼 NCS Career - {request_type}

{response.text}

🔗 NCS: https://www.ncs.gov.in
📞 Helpline: 1800-420-1510"""


class ENAMAgent(BaseAgent):
    """e-NAM agricultural market and mandi price agent."""

    role = "e-nam"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "price_query")
        commodity = context.get("commodity", "not specified")
        state = context.get("state", "unknown")
        market = context.get("market", "not specified")

        prompt = f"""e-NAM Agricultural Market Assistant
Request: {request_type}
Commodity: {commodity}
State: {state}
Market: {market}

Provide:
1. e-NAM registration (farmer/trader)
2. Price discovery (arrival, modal, max)
3. Market search by state
4. Quality testing (NABL labs)
5. Warehouse receipt trading
6. Price history and trends
7. MSP comparison
8. Buyer search
9. Payment settlement process
10. APMC reform status
11. Model mandi license
12. Interstate trade rules"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are an e-NAM agricultural market assistant for Indian farmers and traders. Provide accurate price information with market linkages.",
        )
        return f"""🌾 e-NAM - {request_type} ({commodity})

{response.text}

🔗 e-NAM: https://enam.gov.in
📞 Kisan Call Centre: 1800-180-1551"""


class SoilHealthAgent(BaseAgent):
    """Soil Health Card and agricultural testing agent."""

    role = "soil-health"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "test_request")
        state = context.get("state", "unknown")
        soil_type = context.get("soil_type", "not specified")
        crop = context.get("crop", "not specified")

        prompt = f"""Soil Health Card Assistant
Request: {request_type}
State: {state}
Soil Type: {soil_type}
Crop: {crop}

Provide:
1. Soil Health Card registration
2. Sample collection process
3. Testing lab search (Govt/AISSMS)
4. Parameters tested (N, P, K, pH, OC)
5. Report interpretation
6. Fertilizer recommendations
7. Micronutrient deficiency treatment
8. Organic farming guidance
9. State-wise soil data
10. Soil testing fee structure
11. Card download process
12. Re-testing schedule"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a Soil Health Card assistant for Indian farmers. Provide accurate soil testing guidance with lab search and fertilizer recommendations.",
        )
        return f"""🌱 Soil Health - {request_type}

{response.text}

🔗 Soil Health Card: https://soilhealth.dac.gov.in
📞 Kisan Call Centre: 1800-180-1551"""


class PMKISANAgent(BaseAgent):
    """PM-KISAN Samman Nidhi farmer benefit agent."""

    role = "pm-kisan"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "status_check")
        farmer_id = context.get("farmer_id", "not provided")
        state = context.get("state", "unknown")

        prompt = f"""PM-KISAN Samman Nidhi Assistant
Request: {request_type}
Farmer ID: {farmer_id[:4] if farmer_id != 'not provided' else 'not provided'}XXXX
State: {state}

Provide:
1. Eligibility criteria (landholding farmers)
2. Registration process (CSC/online)
3. Installment status check (₹6000/year)
4. eKYC requirements
5. Bank account linking
6. Aadhaar verification status
7. Beneficiary search by name
8. Common rejection reasons
9. Appeal/grievance process
10. Land Seeding status
11. PFMS payment tracking
12. State-wise scheme status"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a PM-KISAN assistant for Indian farmers. Provide accurate installment status and registration guidance.",
        )
        return f"""🌾 PM-KISAN - {request_type}

{response.text}

🔗 PM-KISAN: https://pmkisan.gov.in
📞 Helpline: 155261 / 011-24300606"""


class SwachhBharatAgent(BaseAgent):
    """Swachh Bharat Mission waste and sanitation agent."""

    role = "swachh-bharat"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "toilet_subsidy")
        state = context.get("state", "unknown")
        urban_rural = context.get("urban_rural", "rural")

        prompt = f"""Swachh Bharat Mission Assistant
Request: {request_type}
State: {state}
Area: {urban_rural} (urban/rural)

Provide:
1. IHHL toilet subsidy application (₹12000)
2. Eligibility criteria
3. Document checklist
4. Online application (SBM-G portal)
5. Payment status tracking
6. ODF village declaration
7. Solid waste management
8. Grey water management
9. Plastic waste collection
10. Cleanliness survey (Swachh Survekshan)
11. Community toilet scheme
12. grievances portal"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a Swachh Bharat Mission assistant. Provide accurate subsidy and sanitation guidance with SBM portal links.",
        )
        return f"""🧹 Swachh Bharat - {request_type}

{response.text}

🔗 SBM-G: https://sbm.gov.in
🔗 SBM-U: https://sbmurban.org"""


class PMAYAgent(BaseAgent):
    """Pradhan Mantri Awas Yojana housing scheme agent."""

    role = "pm-awas"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "eligibility")
        scheme = context.get("scheme", "PMAY-G")
        state = context.get("state", "unknown")
        income = context.get("annual_income", "not specified")

        prompt = f"""PM Awas Yojana Housing Assistant
Request: {request_type}
Scheme: {scheme} (PMAY-G/PMAY-U)
State: {state}
Income: ₹{income}

Provide:
1. Scheme selection (Rural/Urban)
2. Eligibility criteria (EWS/LIG/MIG)
3. Income certificate requirement
4. Beneficiary search
5. Application process (online/CSC)
6. Subsidy amount (₹1.2L-2.67L)
7. Interest subsidy (CLSS)
8. List check (FTO status)
9. Construction progress tracking
10. Document checklist
11. Grievance filing
12. State-specific top-up schemes"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a PM Awas Yojana assistant. Provide accurate housing scheme guidance with eligibility and subsidy information.",
        )
        return f"""🏠 PM Awas - {request_type} ({scheme})

{response.text}

🔗 PMAY-G: https://pmayg.nic.in
🔗 PMAY-U: https://pmaymis.gov.in"""


class CoWINVaccineAgent(BaseAgent):
    """CoWIN vaccination booking and certificate agent."""

    role = "cowin-vaccine"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "certificate")
        vaccine_type = context.get("vaccine_type", "any")
        state = context.get("state", "unknown")

        prompt = f"""CoWIN Vaccination Assistant
Request: {request_type}
Vaccine: {vaccine_type}
State: {state}

Provide:
1. Registration process (mobile + Aadhaar)
2. Slot search by PIN/location
3. Appointment booking
4. Vaccination center list
5. Certificate download/update
6. Correction in certificate
7. International travel certificate
8. Booster/precaution dose info
9. Child vaccination (15-17 years)
10. Adverse event reporting
11. Vaccination status check
12. QR code verification"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a CoWIN vaccination assistant. Provide accurate booking and certificate guidance with portal links.",
        )
        return f"""💉 CoWIN - {request_type}

{response.text}

🔗 CoWIN: https://www.cowin.gov.in
📞 Helpline: 104 / 1075"""


class DigiYatraAgent(BaseAgent):
    """DigiYatra biometric airport travel agent."""

    role = "digi-yatra"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "registration")
        airport = context.get("airport", "not specified")

        prompt = f"""DigiYatra Biometric Travel Assistant
Request: {request_type}
Airport: {airport}

Provide:
1. DigiYatra app registration
2. Face enrollment process
3. Document verification (Aadhaar)
4. Supported airports list
5. Gate entry process (e-gate)
6. Domestic flight setup
7. International travel (coming soon)
8. Privacy and data retention
9. Troubleshooting failed scans
10. App permissions setup
11. Family member enrollment
12. Opt-out and data deletion"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a DigiYatra assistant. Provide accurate biometric enrollment and airport navigation guidance.",
        )
        return f"""✈️ DigiYatra - {request_type}

{response.text}

🔗 DigiYatra: https://www.digiyatra.com
🔗 BCAS: https://bcas.gov.in"""


class NationalScholarshipAgent(BaseAgent):
    """National Scholarship Portal (NSP) application agent."""

    role = "national-scholarship"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "application")
        scholarship_type = context.get("scholarship_type", "pre-matric")
        state = context.get("state", "unknown")
        category = context.get("category", "general")

        prompt = f"""National Scholarship Portal Assistant
Request: {request_type}
Type: {scholarship_type} (pre-matric/post-matric/top-up)
State: {state}
Category: {category}

Provide:
1. NSP registration process
2. Scheme search by state/central
3. Eligibility criteria
4. Document checklist
5. Application form filling
6. Institution verification
7. Status tracking (Institute→District→State)
8. Scholarship amount details
9. Renewal process
10. Aadhaar-linked bank account
11. Disbursement timeline
12. Helpdesk and grievance"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a National Scholarship Portal assistant for Indian students. Provide accurate application guidance with scheme matching.",
        )
        return f"""🎓 NSP Scholarship - {request_type}

{response.text}

🔗 NSP: https://scholarships.gov.in
📞 NSP Helpline: 0120-6619540"""


class JanAushadhiAgent(BaseAgent):
    """Jan Aushadhi generic medicine and pharmacy agent."""

    role = "jan-aushadhi"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "medicine_search")
        medicine_name = context.get("medicine_name", "not specified")
        state = context.get("state", "unknown")

        prompt = f"""Jan Aushadhi Generic Medicine Assistant
Request: {request_type}
Medicine: {medicine_name}
State: {state}

Provide:
1. Generic medicine search by therapeutic class
2. Price comparison (branded vs generic)
3. Jan Aushadhi Kendra locator
4. Quality certification (WHO-GMP)
5. Scheme benefits (70-90% cheaper)
6. Franchise application process
7. Medicine availability check
8. Side effects information
9. Doctor prescription requirement
10. Online ordering (where available)
11. Return/refund policy
12. Health camp information"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a Jan Aushadhi assistant. Provide accurate generic medicine guidance with pricing and pharmacy locator.",
        )
        return f"""💊 Jan Aushadhi - {request_type}

{response.text}

🔗 Jan Aushadhi: https://janaushadhi.gov.in
📞 Helpline: 1800-180-1551"""


class LegalServicesAuthorityAgent(BaseAgent):
    """NALSA free legal aid and Lok Adalat agent."""

    role = "nalsa-legal"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "legal_aid")
        state = context.get("state", "unknown")
        income = context.get("annual_income", "not specified")

        prompt = f"""NALSA Legal Aid & Lok Adalat Assistant
Request: {request_type}
State: {state}
Income: ₹{income}

Provide:
1. Legal aid eligibility (income criteria)
2. Free lawyer entitlement
3. District Legal Services Authority search
4. Application process
5. Lok Adalat schedule
6. Pre-litigation mediation
7. Women/child/divyangjan special aid
8. Legal awareness camps
9. Case status through DLSA
10. Court fee exemption
11. Victim compensation scheme
12. Mediation centre locator"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a NALSA legal aid assistant. Provide accurate free legal service guidance with DLSA contact and eligibility.",
        )
        return f"""⚖️ Legal Aid - {request_type}

{response.text}

🔗 NALSA: https://nalsa.gov.in
📞 Legal Aid: 15100
📞 Emergency: 112"""


class PMSuryaGharAgent(BaseAgent):
    """PM Surya Ghar rooftop solar subsidy agent."""

    role = "pm-surya-ghar"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "subsidy_calc")
        state = context.get("state", "unknown")
        roof_area = context.get("roof_area_sqft", "not specified")
        monthly_bill = context.get("monthly_bill", "not specified")

        prompt = f"""PM Surya Ghar Rooftop Solar Assistant
Request: {request_type}
State: {state}
Roof Area: {roof_area} sq ft
Monthly Bill: ₹{monthly_bill}

Provide:
1. System size recommendation (kW)
2. Subsidy calculation (₹30K-78K)
3. Estimated savings (25 years)
4. Vendor selection criteria
5. DISCOM application process
6. Net metering application
7. Loan options (solar-specific)
8. Empaneled vendor search
9. Installation timeline
10. Maintenance requirements
11. Performance monitoring
12. State-specific incentives"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a PM Surya Ghar solar assistant. Provide accurate subsidy calculations and vendor selection guidance.",
        )
        return f"""☀️ PM Surya Ghar - {request_type}

{response.text}

🔗 PM Surya Ghar: https://pmsuryaghar.gov.in
📞 DISCOM: Check local DISCOM"""


class eDistrictAgent(BaseAgent):
    """e-District certificate and services agent."""

    role = "e-district"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "certificate")
        certificate_type = context.get("certificate_type", "income")
        state = context.get("state", "unknown")

        prompt = f"""e-District Certificate Services Assistant
Request: {request_type}
Certificate: {certificate_type}
State: {state}

Provide:
1. Certificate type selection (income, caste, domicile, etc.)
2. Eligibility criteria
3. Document checklist
4. Online application process (e-District portal)
5. CSC application option
6. Fee structure
7. Verification process
8. Download certificate
9. Certificate validation (QR-based)
10. Correction process
11. Status tracking
12. Grievance redressal"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are an e-District services assistant. Provide accurate certificate application guidance with state portal links.",
        )
        return f"""📋 e-District - {request_type} ({certificate_type})

{response.text}

🔗 e-District: https://edistrict.gov.in
🔗 State Portals: Check respective state e-District website"""


class IRCTCAgent(BaseAgent):
    """IRCTC tourism, e-catering, and booking agent."""

    role = "irctc-tourism"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "tourism_train")
        train_type = context.get("train_type", "maharajas")
        destination = context.get("destination", "not specified")

        prompt = f"""IRCTC Tourism & E-Catering Assistant
Request: {request_type}
Train Type: {train_type}
Destination: {destination}

Provide:
1. Luxury train options (Maharajas Express, Golden Chariot)
2. Bharat Darshan trains
3. Tourist train packages
4. E-catering service list
5. IRCTC tourism portal navigation
6. Package details and pricing
7. Booking process
8. Cancellation policy
9. Special diet options
10. Group booking discounts
11. Seasonal packages
12. Foreign tourist quotas"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are an IRCTC tourism assistant. Provide accurate luxury train and tourism package guidance with booking steps.",
        )
        return f"""🚂 IRCTC Tourism - {request_type}

{response.text}

🔗 IRCTC Tourism: https://www.irctctourism.com
🔗 E-Catering: https://www.ecatering.irctc.co.in"""


class SkillBatch4Registration:
    """Register all Batch 4 India skills."""

    @staticmethod
    def register(registry: SkillRegistry, config: ArchonConfig, provider_router: ProviderRouter) -> None:
        skills = [
            SkillDefinition(
                name="digilocker",
                description="Digilocker document storage, fetch, and verification for Indian citizens.",
                trigger_patterns=["digilocker", "digital.*document", "mParivahan"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="e-shram",
                description="e-Shram worker registration, UAN card, and social security schemes.",
                trigger_patterns=["e-shram", "eshram", "uan.*card", "unorganized.*worker"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="ration-card",
                description="Ration card application, PDS, and food security entitlements.",
                trigger_patterns=["ration card", "pds", "fair price shop", "food security"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="gas-subsidy",
                description="PM Ujjwala Yojana, LPG subsidy, and gas connection services.",
                trigger_patterns=["gas subsidy", "ujjwala", "lpg.*subsidy", "cooking gas"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="umang",
                description="UMANG app government services discovery and navigation.",
                trigger_patterns=["umang", "government.*app", "one.*app.*services"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="ceir",
                description="CEIR lost/stolen mobile blocking, tracking, and recovery.",
                trigger_patterns=["lost.*phone", "stolen.*mobile", "ceir", "block.*imei"],
                version="1.0.0",
                provider_preference="primary",
                cost_tier="standard",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="ncs-career",
                description="National Career Service job search and career guidance.",
                trigger_patterns=["job search", "career.*guidance", "ncs.*job", "employment"],
                version="1.0.0",
                provider_preference="openai",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="e-nam",
                description="e-NAM agricultural market prices and mandi information.",
                trigger_patterns=["mandi price", "e-nam", "enam", "agricultural.*market"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="soil-health",
                description="Soil Health Card testing, recommendations, and lab search.",
                trigger_patterns=["soil.*health", "soil test", "fertilizer.*recommendation"],
                version="1.0.0",
                provider_preference="openai",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="pm-kisan",
                description="PM-KISAN Samman Nidhi farmer installment status and registration.",
                trigger_patterns=["pm-kisan", "pmkisan", "kisan.*nidhi", "farmer.*installment"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="swachh-bharat",
                description="Swachh Bharat Mission toilet subsidy and sanitation services.",
                trigger_patterns=["swachh bharat", "toilet.*subsidy", "sbm", "odf"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="pm-awas",
                description="PM Awas Yojana housing subsidy and application guidance.",
                trigger_patterns=["pm awas", "pmay", "housing.*scheme", "affordable.*housing"],
                version="1.0.0",
                provider_preference="primary",
                cost_tier="standard",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="cowin-vaccine",
                description="CoWIN vaccination booking, certificate, and booster dose guidance.",
                trigger_patterns=["cowin", "vaccination", "vaccine.*certificate", "booster dose"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="digi-yatra",
                description="DigiYatra biometric airport enrollment and navigation.",
                trigger_patterns=["digi yatra", "digiyatra", "biometric.*airport"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="national-scholarship",
                description="National Scholarship Portal scheme search and application.",
                trigger_patterns=["national scholarship", "nsp", "scholarship.*portal"],
                version="1.0.0",
                provider_preference="openai",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="jan-aushadhi",
                description="Jan Aushadhi generic medicine search and pharmacy locator.",
                trigger_patterns=["jan aushadhi", "generic.*medicine", "cheaper.*medicine"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="nalsa-legal",
                description="NALSA free legal aid, Lok Adalat, and mediation services.",
                trigger_patterns=["free legal aid", "nalsa", "lok adalat", "legal.*aid"],
                version="1.0.0",
                provider_preference="primary",
                cost_tier="standard",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="pm-surya-ghar",
                description="PM Surya Ghar rooftop solar subsidy and installation guidance.",
                trigger_patterns=["solar subsidy", "pm surya ghar", "rooftop solar"],
                version="1.0.0",
                provider_preference="openai",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="e-district",
                description="e-District certificate services (income, caste, domicile).",
                trigger_patterns=["e-district", "income certificate", "caste certificate", "domicile"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="irctc-tourism",
                description="IRCTC tourism trains, packages, and e-catering services.",
                trigger_patterns=["maharajas express", "irctc tourism", "golden chariot", "e-catering"],
                version="1.0.0",
                provider_preference="openai",
                cost_tier="low",
                state="ACTIVE",
            ),
        ]

        for skill in skills:
            registry.register(skill)
