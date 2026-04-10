"""India-specific skill implementations for ARCHON - Batch 3 (20+ new skills)."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import BaseAgent
from archon.config import ArchonConfig
from archon.providers import ProviderRouter
from archon.skills.skill_registry import SkillDefinition, SkillRegistry


class RailwayAssistantAgent(BaseAgent):
    """Indian Railways ticketing, PNR, and train status agent."""

    role = "railway-assistant"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "pnr_status")
        pnr = context.get("pnr_number", "")
        train_number = context.get("train_number", "")
        from_station = context.get("from_station", "")
        to_station = context.get("to_station", "")
        travel_date = context.get("travel_date", "")

        prompt = f"""Indian Railways Assistant
Request: {request_type}
PNR: {pnr}
Train: {train_number}
From: {from_station} → To: {to_station}
Date: {travel_date}

Provide:
1. PNR status interpretation (CNF/RAC/WL)
2. Train schedule and running days
3. Fare calculation with quotas (Tatkal, Ladies, Senior Citizen)
4. Alternative trains if waitlisted
5. Platform and coach position info
6. Cancellation and refund rules
7. e-Catering options
8. Station amenities
9. Tourism train options (Maharajas Express, etc.)
10. UTS platform ticket info"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a Indian Railways assistant. Provide accurate PNR status, train schedules, and booking guidance. Include IRCTC portal links.",
        )
        return f"""🚂 Indian Railways - {request_type}

{response.text}

🔗 IRCTC: https://www.irctc.co.in
🔗 NTES: https://enquiry.indianrail.gov.in
📞 Rail Sutra: 139"""


class PassportAssistantAgent(BaseAgent):
    """Passport application and tracking agent."""

    role = "passport-assistant"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "new_application")
        passport_type = context.get("passport_type", "fresh")
        applicant_type = context.get("applicant_type", "adult")
        state = context.get("state", "unknown")
        urgency = context.get("urgency", "normal")

        prompt = f"""Passport Services Assistant
Request: {request_type}
Type: {passport_type} | Applicant: {applicant_type}
State: {state} | Urgency: {urgency}

Provide:
1. Eligibility check
2. Document checklist (birth proof, address proof, photos)
3. Passport Office jurisdiction
4. Online application steps (Passport Seva portal)
5. Appointment booking process
6. Fee structure (normal/tatkal)
7. Police verification process
8. Timeline estimate
9. Track application status
10. Reissue/renewal criteria
11. Minor/Senior Citizen special rules
12. Diplomatic/Official passport info"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a passport services assistant for Indian citizens. Provide accurate application guidance with document checklists and Passport Seva portal steps.",
        )
        return f"""🛂 Passport Services - {request_type}

{response.text}

🔗 Passport Seva: https://www.passportindia.gov.in
📞 Helpline: 1800-258-1800"""


class AyushmanBharatAgent(BaseAgent):
    """Ayushman Bharat PM-JAY eligibility and hospital finder."""

    role = "ayushman-bharat"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "eligibility")
        state = context.get("state", "unknown")
        family_income = context.get("family_income", "not specified")
        category = context.get("category", "not specified")
        location = context.get("location", "not specified")

        prompt = f"""Ayushman Bharat PM-JAY Assistant
Request: {request_type}
State: {state}
Family Income: ₹{family_income}
Category: {category}
Location: {location}

Provide:
1. Eligibility check (SECC/ration card based)
2. Coverage details (₹5 lakh per family per year)
3. Beneficiary card download process
4. Empanelled hospital search
5. Treatment packages and rates
6. Cashless treatment process
7. Claim filing for reimbursement
8. Grievance redressal
9. State-specific health schemes
10. PMJAY MUDRA card info
11. Arogya Setu integration"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are an Ayushman Bharat PM-JAY assistant. Provide eligibility guidance, hospital search, and claim process information for Indian citizens.",
        )
        return f"""🏥 Ayushman Bharat - {request_type}

{response.text}

🔗 PM-JAY: https://pmjay.gov.in
📞 Helpline: 14555
📱 Arogya Setu App"""


class VoterIDAssistantAgent(BaseAgent):
    """Voter ID registration, correction, and EPIC agent."""

    role = "voter-id"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "new_registration")
        state = context.get("state", "unknown")
        age = context.get("age", "not specified")
        epic_number = context.get("epic_number", "")

        prompt = f"""Voter ID Services Assistant
Request: {request_type}
State: {state}
Age: {age}
EPIC Number: {epic_number}

Provide:
1. Eligibility criteria (age 18+, citizen)
2. Form selection (Form 6/new, Form 8/correction, Form 7/deletion)
3. Document checklist
4. Online registration (NVSP portal)
5. Booth/Scheme officer lookup
6. Correction process
7. Duplicate EPIC request
8. Tracking application status
9. Polling booth search
10. Postal ballot eligibility
11. Voter helpline app"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a Voter ID assistant for Indian citizens. Provide accurate voter registration guidance with NVSP portal links and form instructions.",
        )
        return f"""🗳️ Voter ID - {request_type}

{response.text}

🔗 NVSP: https://www.nvsp.in
📞 Voter Helpline: 1950
📱 Voter Helpline App"""


class PANAadhaarAgent(BaseAgent):
    """PAN-Aadhaar linking, correction, and download agent."""

    role = "pan-aadhaar"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "linking")
        action = context.get("action", "link")
        pan = context.get("pan", "not provided")

        prompt = f"""PAN-Aadhaar Services Assistant
Request: {request_type}
Action: {action}
PAN: {pan[:4]}XXXX

Provide:
1. Linking status check
2. Linking process (e-filing portal)
3. Fee/penalty structure
4. Correction in PAN (Form 49A/CSF)
5. Correction in Aadhaar (UIDAI portal)
6. PAN download/print
7. Aadhaar download
8. Name mismatch resolution
9. Nominee registration
10. Last date alerts
11. Consequences of non-linking"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are a PAN-Aadhaar services assistant. Provide accurate linking guidance with e-filing and UIDAI portal steps.",
        )
        return f"""🆔 PAN-Aadhaar - {request_type}

{response.text}

🔗 e-Filing: https://www.incometax.gov.in
🔗 UIDAI: https://uidai.gov.in"""


class WeatherIMDAgent(BaseAgent):
    """IMD weather forecast and disaster alert agent."""

    role = "weather-imd"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        location = context.get("location", "not specified")
        forecast_type = context.get("forecast_type", "daily")
        state = context.get("state", "unknown")

        prompt = f"""IMD Weather Assistant
Location: {location}
State: {state}
Forecast Type: {forecast_type}

Provide:
1. Current weather conditions
2. 7-day forecast
3. Temperature and humidity
4. Rainfall probability
5. Wind speed and direction
6. UV index
7. Air quality (AQI)
8. Agricultural weather advisory
9. Disaster alerts (flood/cyclone/drought)
10. Monsoon status (if applicable)
11. City-wise comparison"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are an IMD weather assistant for Indian users. Provide accurate forecasts with agricultural and safety advisories.",
        )
        return f"""🌤️ Weather - {location}

{response.text}

🔗 IMD: https://mausam.imd.gov.in
🔗 AQI: https://app.cpcbccr.com
📞 Disaster Helpline: 1078"""


class BankingComplaintAgent(BaseAgent):
    """Banking complaint, ombudsman, and account services agent."""

    role = "banking-complaint"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        complaint_type = context.get("complaint_type", "general")
        bank_name = context.get("bank_name", "not specified")
        state = context.get("state", "unknown")

        prompt = f"""Banking Complaint Assistant
Complaint Type: {complaint_type}
Bank: {bank_name}
State: {state}

Provide:
1. Complaint category selection
2. Internal grievance process (branch → nodal → appellate)
3. Banking Ombudsman filing (RBI CMS portal)
4. Document checklist
5. Timeline expectations
6. Compensation rules
7. Digital payment complaints (UPI/cards)
8. Account freezing/unfreezing
9. Lost card/cheque stop
10. KYC document submission
11. Loan complaint resolution"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a banking complaint assistant for Indian customers. Provide accurate grievance redressal guidance with RBI Ombudsman process.",
        )
        return f"""🏦 Banking Complaint - {complaint_type}

{response.text}

🔗 RBI CMS: https://cms.rbi.org.in
📞 RBI Helpline: 14448
📞 Banking Ombudsman: 1800-110-000"""


class ElectricityUtilityAgent(BaseAgent):
    """Electricity connection, bill, and complaint agent."""

    role = "electricity-utility"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "bill_inquiry")
        discom = context.get("discom", "not specified")
        state = context.get("state", "unknown")
        consumer_number = context.get("consumer_number", "not provided")

        prompt = f"""Electricity Utility Assistant
Request: {request_type}
DISCOM: {discom}
State: {state}
Consumer Number: {consumer_number}

Provide:
1. Bill breakdown (fixed + variable + subsidy)
2. Online payment options
3. New connection process
4. Load enhancement request
5. Meter replacement/rectification
6. Complaint filing (high bill, no supply, etc.)
7. Solar net metering application
8. Subsidy schemes (PM Surya Ghar)
9. Energy saving tips
10. Regulatory commission complaint (ERC)
11. EV charging station info"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are an electricity utility assistant for Indian consumers. Provide bill guidance, complaint process, and subsidy information.",
        )
        return f"""⚡ Electricity - {request_type} ({discom})

{response.text}

🔗 UDAY Portal: https://uday.gov.in
📞 DISCOM Helpline: Check local DISCOM
📞 Consumer Forum: 1800-11-4000"""


class PoliceServiceAgent(BaseAgent):
    """Police services, FIR, and character certificate agent."""

    role = "police-service"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "fir_filing")
        state = context.get("state", "unknown")
        district = context.get("district", "not specified")
        urgency = context.get("urgency", "normal")

        prompt = f"""Police Services Assistant
Request: {request_type}
State: {state}
District: {district}
Urgency: {urgency}

Provide:
1. FIR filing process (zero FIR, e-FIR)
2. Online FIR portal selection
3. Required documents
4. FIR copy entitlement
5. Character certificate process
6. Police verification for passport/jobs
7. Tenant verification
8. Lost article reporting
9. Cyber crime complaint (1930)
10. Women helpline (1091/181)
11. Senior citizen registration
12. Protest/event permission"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a police services assistant for Indian citizens. Provide accurate FIR filing guidance with cyber crime and women safety resources.",
        )
        return f"""👮 Police Services - {request_type}

{response.text}

🔗 CCTNS: https://cctns.nic.in
📞 Emergency: 100
📞 Women: 1091
📞 Cyber Crime: 1930"""


class CourtEfileAgent(BaseAgent):
    """e-Courts case tracking and e-filing agent."""

    role = "court-efile"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "case_status")
        court_level = context.get("court_level", "district")
        state = context.get("state", "unknown")
        case_number = context.get("case_number", "")

        prompt = f"""Court e-Filing & Case Tracking Assistant
Request: {request_type}
Court Level: {court_level}
State: {state}
Case Number: {case_number}

Provide:
1. Case status check (e-Courts portal)
2. Cause list for the day
3. Order/judgment download
4. e-Filing process (filing, fees, verification)
5. Case filing number generation
6. Advocate registration
7. Bail application guidance
8. Case transfer process
9. Certified copy request
10. Legal aid eligibility
11. Lok Adalat info
12. Mediation center lookup"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are an e-Courts assistant for Indian litigants. Provide accurate case tracking, e-filing guidance, and court procedure information.",
        )
        return f"""⚖️ Court Services - {request_type}

{response.text}

🔗 e-Courts: https://ecourts.gov.in
🔗 e-Filing: https://efiling.ecourts.gov.in
📞 Legal Services: 15100"""


class TaxITRAgent(BaseAgent):
    """Income Tax return filing and refund agent."""

    role = "tax-itr"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "itr_filing")
        itr_form = context.get("itr_form", "ITR-1")
        financial_year = context.get("financial_year", "2024-25")
        taxpayer_type = context.get("taxpayer_type", "individual")

        prompt = f"""Income Tax ITR Assistant
Request: {request_type}
Form: {itr_form}
Financial Year: {financial_year}
Taxpayer Type: {taxpayer_type}

Provide:
1. ITR form selection guide
2. Eligibility criteria for each form
3. Filing steps (e-filing portal)
4. Document checklist (Form 16, bank statements, etc.)
5. Deductions (80C, 80D, 80E, etc.)
6. Tax computation worksheet
7. Tax regime comparison (old vs new)
8. Refund tracking
9. Notice response guidance
10. Revised return process
11. Late filing penalties
12. Advance tax schedule"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are an Income Tax ITR assistant for Indian taxpayers. Provide accurate return filing guidance with deduction calculations and portal steps.",
        )
        return f"""💰 Income Tax - {request_type} ({itr_form})

{response.text}

🔗 e-Filing: https://www.incometax.gov.in
📞 TIN Helpline: 1800-103-0025"""


class LandRecordAgent(BaseAgent):
    """Land records, property tax, and registration agent."""

    role = "land-record"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "land_records")
        state = context.get("state", "unknown")
        district = context.get("district", "not specified")
        village = context.get("village", "not specified")

        prompt = f"""Land Records & Registration Assistant
Request: {request_type}
State: {state}
District: {district}
Village: {village}

Provide:
1. Khata/Khewat number search
2. Jamabandi copy download
3. Encumbrance Certificate (EC)
4. Property registration process
5. Stamp duty calculation
6. Registry office lookup
7. Mutation application
8. Property tax payment
9. Land conversion process
10. RERA registration check
11. Land ceiling verification
12. Agriculture land restrictions"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a land records and registration assistant for Indian property owners. Provide accurate guidance on state-specific land records portals.",
        )
        return f"""🏡 Land Records - {request_type} ({state})

{response.text}

🔗 DILRMP: https://dilrmp.gov.in
🔗 State Portals: Check respective state revenue website"""


class EPFOAgent(BaseAgent):
    """EPFO PF, pension, and withdrawal agent."""

    role = "epfo"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "pf_withdrawal")
        uan = context.get("uan", "not provided")
        employer = context.get("employer", "not specified")

        prompt = f"""EPFO PF & Pension Assistant
Request: {request_type}
UAN: {uan[:4]}XXXX
Employer: {employer}

Provide:
1. UAN activation and KYC
2. PF balance check (passbook)
3. Form 31 (advance withdrawal)
4. Form 19 (final settlement)
5. Form 10C (pension withdrawal)
6. Online claim process (UAN portal)
7. Transfer claim (Form 13)
8. Pension status check
9. EDLI benefits
10. Grievance (EPFiGMS)
11. e-Nomination process
12. Employee vs employer share"""

        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt="You are an EPFO PF assistant for Indian employees. Provide accurate withdrawal guidance with UAN portal steps and form instructions.",
        )
        return f"""💼 EPFO - {request_type}

{response.text}

🔗 EPFO Unified Portal: https://unifiedportal-mem.epfindia.gov.in
🔗 Passbook: https://passbook.epfindia.gov.in
📞 EPFO Helpline: 1800-118-009"""


class SeniorCitizenAgent(BaseAgent):
    """Senior citizen services, pension, and welfare schemes."""

    role = "senior-citizen"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "pension")
        state = context.get("state", "unknown")
        age = context.get("age", "not specified")
        income = context.get("income", "not specified")

        prompt = f"""Senior Citizen Services Assistant
Request: {request_type}
State: {state}
Age: {age}
Income: ₹{income}

Provide:
1. Old Age Pension schemes (IGNOAPS, state schemes)
2. Application process
3. Senior Citizen card/ID
4. Income certificate process
5. Ayushman Bharat eligibility (60+ automatic)
6. Life certificate (Jeevan Pramaan)
7. Railway/Air travel concessions
8. Bank account nominee rules
9. Property rights and maintenance
10. Elder abuse helpline
11. Old age home search
12. Day care centre lookup"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a senior citizen services assistant for Indian elders. Provide accurate pension, welfare scheme, and service guidance.",
        )
        return f"""👴 Senior Citizen Services - {request_type}

{response.text}

🔗 SJE: https://socialjustice.gov.in
📞 Elders Helpline: 14567
📞 Emergency: 112"""


class DisabilityAgent(BaseAgent):
    """Disability (Divyangjan) certificate and welfare agent."""

    role = "disability"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "certificate")
        disability_type = context.get("disability_type", "not specified")
        state = context.get("state", "unknown")

        prompt = f"""Disability (Divyangjan) Services Assistant
Request: {request_type}
Disability Type: {disability_type}
State: {state}

Provide:
1. Disability certificate process (CMO office)
2. UDID card application
3. 21 recognized disabilities
4. Assessment hospital search
5. Pension schemes (ADIP, state pensions)
6. Employment quota benefits
7. Education concessions
8. Travel concessions
9. Tax benefits (80U, 80DD)
10. Assistive device schemes
11. Grievance redressal
12. NCPEDP resources"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a disability services assistant for Indian Divyangjan. Provide accurate certificate, UDID, and welfare scheme guidance.",
        )
        return f"""♿ Disability Services - {request_type}

{response.text}

🔗 UDID: https://www.udid.gov.in
🔗 ADIP: https://socialjustice.gov.in
📞 Divyangjan Helpline: 1800-11-5656"""


class CyberCrimeAgent(BaseAgent):
    """Cyber crime reporting and digital fraud agent."""

    role = "cyber-crime"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        fraud_type = context.get("fraud_type", "online_fraud")
        amount = context.get("amount", "not specified")
        platform = context.get("platform", "not specified")

        prompt = f"""Cyber Crime Reporting Assistant
Fraud Type: {fraud_type}
Amount: ₹{amount}
Platform: {platform}

Provide:
1. Immediate actions (block card, change passwords)
2. National Cyber Crime Portal reporting
3. FIR filing (online/offline)
4. Evidence preservation
5. Bank chargeback request
6. Transaction reversal timeline
7. Social media account recovery
8. Identity theft protection
9. Romance scam reporting
10. Cryptocurrency fraud handling
11. Sextortion reporting
12. Compensation eligibility"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a cyber crime assistant for Indian victims. Provide immediate action steps and accurate reporting guidance with portal links.",
        )
        return f"""🚨 Cyber Crime - {fraud_type}

{response.text}

🔗 Cyber Crime Portal: https://cybercrime.gov.in
📞 Helpline: 1930
📧 Email: cybercrime@gov.in"""


class MSMEUdyamAgent(BaseAgent):
    """MSME Udyam registration and scheme agent."""

    role = "msme-udyam"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "registration")
        business_type = context.get("business_type", "micro")
        state = context.get("state", "unknown")

        prompt = f"""MSME Udyam Registration & Schemes Assistant
Request: {request_type}
Business Type: {business_type}
State: {state}

Provide:
1. Udyam registration process
2. Micro/Small/Medium classification
3. Required documents (Aadhaar, PAN, bank)
4. Benefits (priority lending, tender, subsidy)
5. Udyam certificate download
6. MSME Sambandh (vendor portal)
7. MSME Samadhan (complaint portal)
8. Government e-Marketplace (GeM) registration
9. CGTMSE loan scheme
10. PMEGP subsidy
11. State MSME schemes
12. Cluster development programs"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are an MSME Udyam assistant for Indian businesses. Provide accurate registration guidance with scheme benefits and portal links.",
        )
        return f"""🏭 MSME Udyam - {request_type}

{response.text}

🔗 Udyam: https://udyamregistration.gov.in
🔗 GeM: https://gem.gov.in
📞 MSME Helpline: 1800-115-565"""


class WaterHarvestAgent(BaseAgent):
    """Rainwater harvesting and water conservation agent."""

    role = "water-harvest"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        request_type = context.get("request_type", "rooftop")
        state = context.get("state", "unknown")
        property_type = context.get("property_type", "residential")
        roof_area = context.get("roof_area_sqft", "not specified")

        prompt = f"""Rainwater Harvesting & Water Conservation Assistant
Request: {request_type}
State: {state}
Property Type: {property_type}
Roof Area: {roof_area} sq ft

Provide:
1. System design (rooftop/campus/community)
2. Components (filter, storage, recharge)
3. Cost estimate
4. Subsidy schemes (state-specific)
5. Mandatory compliance check
6. Installation process
7. Maintenance schedule
8. Groundwater recharge benefits
9. Water testing requirements
10. Government grants available
11. Expert/vendor directory
12. Rainfall data for location"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="You are a rainwater harvesting assistant for Indian property owners. Provide system design guidance with subsidy information.",
        )
        return f"""💧 Water Harvesting - {request_type}

{response.text}

🔗 Jal Shakti: https://jalshakti-dowr.gov.in
🔗 CGWB: https://cgwb.gov.in"""


class SkillBatch3Registration:
    """Register all Batch 3 India skills."""

    @staticmethod
    def register(
        registry: SkillRegistry, config: ArchonConfig, provider_router: ProviderRouter
    ) -> None:
        skills = [
            SkillDefinition(
                name="railway-assistant",
                description="PNR status, train schedules, booking guidance for Indian Railways.",
                trigger_patterns=["pnr", "train", "railway", "irctc", "tatkal", "platform"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="passport-assistant",
                description="Passport application, renewal, and status tracking for Indian citizens.",
                trigger_patterns=["passport", "passport seva", "police verification.*passport"],
                version="1.0.0",
                provider_preference="anthropic",
                cost_tier="standard",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="ayushman-bharat",
                description="Ayushman Bharat PM-JAY eligibility and hospital finder.",
                trigger_patterns=["ayushman", "pm-jay", "pmjay", "health insurance.*poor"],
                version="1.0.0",
                provider_preference="openai",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="voter-id",
                description="Voter ID registration, correction, EPIC card services.",
                trigger_patterns=["voter id", "voter card", "epic", "electoral roll", "nvsp"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="pan-aadhaar",
                description="PAN-Aadhaar linking, correction, and document download.",
                trigger_patterns=["pan.*aadhaar", "aadhaar.*pan", "pan link", "e-filing"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="weather-imd",
                description="IMD weather forecast, agricultural advisory, and disaster alerts.",
                trigger_patterns=["weather", "forecast", "monsoon", "imd", "rain.*tomorrow"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="banking-complaint",
                description="Banking complaint, RBI ombudsman, and grievance redressal.",
                trigger_patterns=["bank.*complaint", "ombudsman", "rbi.*grievance", "atm.*fail"],
                version="1.0.0",
                provider_preference="anthropic",
                cost_tier="standard",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="electricity-utility",
                description="Electricity bill, connection, complaint, and solar net metering.",
                trigger_patterns=["electricity", "electric bill", "discom", "power.*outage"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="police-service",
                description="FIR filing, character certificate, cyber crime, and police verification.",
                trigger_patterns=[
                    "fir",
                    "police complaint",
                    "character certificate",
                    "cyber crime",
                ],
                version="1.0.0",
                provider_preference="anthropic",
                cost_tier="standard",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="court-efile",
                description="e-Courts case tracking, e-filing, and legal procedure guidance.",
                trigger_patterns=[
                    "case status",
                    "cause list",
                    "ecourts",
                    "e-filing",
                    "court order",
                ],
                version="1.0.0",
                provider_preference="anthropic",
                cost_tier="standard",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="tax-itr",
                description="Income Tax ITR filing, refund tracking, and deduction guidance.",
                trigger_patterns=["income tax", "itr", "tax return", "tds", "form 16"],
                version="1.0.0",
                provider_preference="anthropic",
                cost_tier="standard",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="land-record",
                description="Land records, property registration, stamp duty, and mutation.",
                trigger_patterns=[
                    "land record",
                    "khata",
                    "jamabandi",
                    "property registration",
                    "ec.*land",
                ],
                version="1.0.0",
                provider_preference="anthropic",
                cost_tier="standard",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="epfo",
                description="EPFO PF withdrawal, pension, and UAN services.",
                trigger_patterns=["pf", "pf withdrawal", "epfo", "uan", "pension.*employee"],
                version="1.0.0",
                provider_preference="fast",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="senior-citizen",
                description="Senior citizen pension, welfare schemes, and services.",
                trigger_patterns=["senior citizen", "old age pension", "elderly", "pension.*60"],
                version="1.0.0",
                provider_preference="openai",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="disability",
                description="Disability certificate, UDID, and Divyangjan welfare schemes.",
                trigger_patterns=["disability", "divyang", "udid", "differently abled", "80u"],
                version="1.0.0",
                provider_preference="openai",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="cyber-crime",
                description="Cyber crime reporting, online fraud, and digital safety.",
                trigger_patterns=["cyber crime", "online fraud", "hacked", "phishing", "otp.*scam"],
                version="1.0.0",
                provider_preference="anthropic",
                cost_tier="standard",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="msme-udyam",
                description="MSME Udyam registration, schemes, and GeM marketplace.",
                trigger_patterns=["udyam", "msme registration", "gem.*marketplace", "mudra loan"],
                version="1.0.0",
                provider_preference="openai",
                cost_tier="low",
                state="ACTIVE",
            ),
            SkillDefinition(
                name="water-harvest",
                description="Rainwater harvesting system design, subsidy, and compliance.",
                trigger_patterns=["rainwater", "water harvesting", "groundwater recharge"],
                version="1.0.0",
                provider_preference="openai",
                cost_tier="low",
                state="ACTIVE",
            ),
        ]

        for skill in skills:
            registry.register(skill)
