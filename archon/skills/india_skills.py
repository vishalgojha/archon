"""India-specific skill implementations for ARCHON."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import BaseAgent
from archon.config import ArchonConfig
from archon.core.types import TaskMode
from archon.providers import ProviderRouter
from archon.skills.skill_registry import SkillDefinition, SkillRegistry


class KisanAdvisoryAgent(BaseAgent):
    """Agriculture advisory agent for Indian farmers."""

    role = "kisan-advisory"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.language_map = {
            "hindi": "hi",
            "marathi": "mr",
            "punjabi": "pa",
            "tamil": "ta",
            "telugu": "te",
            "kannada": "kn",
            "gujarati": "gu",
            "bengali": "bn",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute kisan advisory task."""
        region = context.get("region", "unknown")
        season = context.get("season", "kharif")
        language = context.get("language", "hindi")
        
        prompt = self._build_advisory_prompt(region, season, context)
        
        # Use pipeline mode for structured analysis
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_system_prompt(language),
        )
        
        return self._format_response(response.content, context)

    def _build_advisory_prompt(
        self,
        region: str,
        season: str,
        context: dict[str, Any],
    ) -> str:
        """Build prompt for crop advisory."""
        soil = context.get("soil_type", "not specified")
        size = context.get("land_size_acres", "not specified")
        
        return f"""किसान सलाह प्रणाली - Kisan Advisory System

Region: {region}
Season: {season}
Soil Type: {soil}
Land Size: {size} acres

Provide:
1. Crop recommendations for current season
2. Weather advisory (check IMD forecasts)
3. Mandi price trends for recommended crops
4. Fertilizer and pesticide recommendations
5. Government scheme eligibility (PM-KISAN, soil health card)

Respond in the language detected from context."""

    def _get_system_prompt(self, language: str) -> str:
        """Get system prompt in regional language."""
        prompts = {
            "hindi": "आप एक भारतीय कृषि विशेषज्ञ हैं। किसानों को व्यावहारिक सलाह दें।",
            "marathi": "आप एक भारतीय कृषि विशेषज्ञ आहात. शेतकऱ्यांना व्यावहारिक सल्ला द्या.",
            "tamil": "நீர் ஒரு இந்திய வேளாண் நிபுணர். விவசாயிகளுக்கு நடைமுறை ஆலோசனை வழங்குங்கள்.",
        }
        return prompts.get(language, "You are an Indian agriculture expert. Provide practical advice to farmers.")

    def _format_response(self, content: str, context: dict[str, Any]) -> str:
        """Format response with actionable items."""
        region = context.get("region", "region")
        return f"""🌾 किसान सलाह - {region}

{content}

⚠️ Disclaimer: Consult local agriculture officer for final decisions.
📞 Kisan Call Centre: 1800-180-1551"""


class HealthcareTriageAgent(BaseAgent):
    """Healthcare triage agent for rural India."""

    role = "healthcare-triage"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.emergency_keywords = [
            "chest pain", "breathing difficulty", "unconscious",
            "severe bleeding", "stroke", "heart attack"
        ]

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute healthcare triage task."""
        symptoms = context.get("symptoms", "")
        duration = context.get("duration_days", "unknown")
        location = context.get("location", "rural")
        
        # Check for emergency
        if self._is_emergency(symptoms):
            return self._emergency_response()
        
        prompt = self._build_triage_prompt(symptoms, duration, location, context)
        
        # Use single mode for fast response
        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt=self._get_triage_system_prompt(),
        )
        
        return self._format_triage_response(response.content, context)

    def _is_emergency(self, symptoms: str) -> bool:
        """Check if symptoms indicate emergency."""
        symptoms_lower = symptoms.lower()
        return any(kw in symptoms_lower for kw in self.emergency_keywords)

    def _emergency_response(self) -> str:
        """Return emergency instructions."""
        return """🚨 MEDICAL EMERGENCY DETECTED

Immediate Actions:
1. Call 108 Ambulance immediately
2. Do not wait for online consultation
3. Go to nearest emergency facility

Emergency Numbers:
- 108: Ambulance (Free)
- 102: Patient Transport
- 112: Emergency Response

⚠️ This is not a diagnosis. Seek immediate medical attention."""

    def _build_triage_prompt(
        self,
        symptoms: str,
        duration: str,
        location: str,
        context: dict[str, Any],
    ) -> str:
        """Build triage prompt."""
        age = context.get("patient_age", "unknown")
        conditions = context.get("existing_conditions", "none")
        
        return f"""Healthcare Triage Assessment

Symptoms: {symptoms}
Duration: {duration} days
Location: {location}
Patient Age: {age}
Existing Conditions: {conditions}

Provide:
1. Triage level (emergency/urgent/routine)
2. Facility recommendation (PHC/CHC/District Hospital)
3. Immediate actions
4. Ayushman Bharat PM-JAY eligibility
5. Warning signs to watch

Be conservative in triage assessment."""

    def _get_triage_system_prompt(self) -> str:
        """Get triage system prompt."""
        return """You are a healthcare triage assistant for rural India. 
Always prioritize patient safety. When in doubt, recommend higher level of care.
Include disclaimers. This is not a diagnosis."""

    def _format_triage_response(self, content: str, context: dict[str, Any]) -> str:
        """Format triage response."""
        location = context.get("location", "location")
        return f"""🏥 Healthcare Triage - {location}

{content}

⚠️ Disclaimer: This is not a diagnosis. Consult a qualified healthcare professional.
📞 National Health Portal: 1800-116-666"""


class ScholarshipApplicationAgent(BaseAgent):
    """Scholarship application guidance agent."""

    role = "scholarship-application"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.schemes = {
            "SC": ["Post-Matric SC", "Pre-Matric SC", "Top Class Education"],
            "ST": ["Post-Matric ST", "Pre-Matric ST", "Top Class Education"],
            "OBC": ["Post-Matric OBC", "Pre-Matric OBC"],
            "EWS": ["EWS Scholarship", "Post-Matric EWS"],
            "General": ["Merit-cum-Means", "Central Scheme"],
        }

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute scholarship application guidance."""
        category = context.get("student_category", "General")
        education_level = context.get("education_level", "unknown")
        state = context.get("state", "unknown")
        income = context.get("family_income", "not specified")
        
        prompt = self._build_scholarship_prompt(category, education_level, state, income)
        
        # Use pipeline mode for structured guidance
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_scholarship_system_prompt(),
        )
        
        return self._format_scholarship_response(response.content, context)

    def _build_scholarship_prompt(
        self,
        category: str,
        education_level: str,
        state: str,
        income: str,
    ) -> str:
        """Build scholarship guidance prompt."""
        return f"""Scholarship Application Assistant

Student Category: {category}
Education Level: {education_level}
State: {state}
Family Income: {income}

Provide:
1. Eligible schemes (National + State)
2. Eligibility criteria for each
3. Document checklist
4. Application steps (NSP portal)
5. Deadlines
6. Renewal requirements
7. Contact information

Include links to official portals."""

    def _get_scholarship_system_prompt(self) -> str:
        """Get scholarship system prompt."""
        return """You are a scholarship application assistant for Indian students.
Provide accurate, up-to-date information. Always link to official portals.
Do not store personal student data."""

    def _format_scholarship_response(self, content: str, context: dict[str, Any]) -> str:
        """Format scholarship response."""
        category = context.get("student_category", "category")
        return f"""📚 Scholarship Guidance - {category}

{content}

🔗 National Scholarship Portal: https://scholarships.gov.in
⚠️ Verify all information on official portals."""


class MSMELoanAgent(BaseAgent):
    """MSME loan assistance agent."""

    role = "msme-loan-assistant"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.mudra_categories = {
            "Shishu": "Up to ₹50,000",
            "Kishore": "₹50,000 to ₹5 Lakh",
            "Tarun": "₹5 Lakh to ₹10 Lakh",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute MSME loan assistance."""
        business_type = context.get("business_type", "unknown")
        loan_amount = context.get("loan_amount_requested", 0)
        state = context.get("state", "unknown")
        turnover = context.get("annual_turnover", "not specified")
        
        prompt = self._build_loan_prompt(business_type, loan_amount, state, turnover)
        
        # Use pipeline mode for multi-stage analysis
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt=self._get_loan_system_prompt(),
        )
        
        return self._format_loan_response(response.content, context)

    def _build_loan_prompt(
        self,
        business_type: str,
        loan_amount: float,
        state: str,
        turnover: str,
    ) -> str:
        """Build loan assistance prompt."""
        return f"""MSME Loan Assistant

Business Type: {business_type}
Loan Amount Requested: ₹{loan_amount:,}
State: {state}
Annual Turnover: {turnover}

Provide:
1. Eligible schemes (MUDRA, CGTMSE, bank loans)
2. MUDRA category (Shishu/Kishore/Tarun)
3. Interest rate range
4. Document checklist (Udyam, GST, financials)
5. Lender recommendations
6. Subsidy details (if applicable)
7. Application timeline
8. PMEGP eligibility

Include calculations where applicable."""

    def _get_loan_system_prompt(self) -> str:
        """Get loan system prompt."""
        return """You are an MSME loan assistant for Indian businesses.
Provide accurate scheme information. Include disclaimers about bank approval.
Never guarantee loan approval."""

    def _format_loan_response(self, content: str, context: dict[str, Any]) -> str:
        """Format loan response."""
        business = context.get("business_type", "business")
        amount = context.get("loan_amount_requested", 0)
        return f"""💰 MSME Loan Assistant - {business}

Requested Amount: ₹{amount:,}

{content}

🔗 Udyam Registration: https://udyamregistration.gov.in
⚠️ Final approval subject to bank verification."""


class GovtFormAgent(BaseAgent):
    """Government form filling assistance agent."""

    role = "govt-form-assistant"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config
        self.form_portals = {
            "Aadhaar": "https://myaadhaar.uidai.gov.in",
            "PAN": "https://www.tin-nsdl.com",
            "Passport": "https://passportindia.gov.in",
            "Voter ID": "https://voters.eci.gov.in",
            "Driving License": "https://parivahan.gov.in",
        }

    async def execute(self, context: dict[str, Any]) -> str:
        """Execute government form assistance."""
        form_type = context.get("form_type", "unknown")
        action = context.get("action_type", "new")
        state = context.get("state", "pan-India")
        
        prompt = self._build_form_prompt(form_type, action, state)
        
        # Use single mode for quick guidance
        response = await self.provider_router.invoke(
            role="fast",
            prompt=prompt,
            system_prompt=self._get_form_system_prompt(),
        )
        
        return self._format_form_response(response.content, context)

    def _build_form_prompt(
        self,
        form_type: str,
        action: str,
        state: str,
    ) -> str:
        """Build form assistance prompt."""
        return f"""Government Form Assistant

Form Type: {form_type}
Action: {action}
State: {state}

Provide:
1. Official portal URL
2. Document checklist
3. Step-by-step guide
4. Fees applicable
5. Processing time
6. Tracking instructions
7. Helpdesk contact

Use simple language. Avoid bureaucratic jargon."""

    def _get_form_system_prompt(self) -> str:
        """Get form system prompt."""
        return """You are a government form assistant for Indian citizens.
Use simple, clear language. Always link to official portals.
Do not collect personal data. Include disclaimers."""

    def _format_form_response(self, content: str, context: dict[str, Any]) -> str:
        """Format form response."""
        form = context.get("form_type", "form")
        action = context.get("action_type", "application")
        portal = self.form_portals.get(form, "official portal")
        return f"""📋 {form} {action.title()} Guide

{content}

🔗 Official Portal: {portal}
📞 UMANG App: Available for most services
⚠️ Verify information on official portal."""


def register_india_skills(registry: SkillRegistry, config: ArchonConfig, provider_router: ProviderRouter) -> None:
    """Register all India-specific skills."""
    skills = [
        SkillDefinition(
            name="kisan-advisory",
            version="1.0.0",
            provider_preference="openai",
            cost_tier="low",
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
            name="scholarship-application",
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
            name="govt-form-assistant",
            version="1.0.0",
            provider_preference="openai",
            cost_tier="low",
            state="active",
        ),
    ]
    
    for skill in skills:
        registry.register(skill)
