"""Startup funding and investor matching skill for Indian entrepreneurs."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import BaseAgent
from archon.config import ArchonConfig
from archon.providers import ProviderRouter
from archon.skills.skill_registry import SkillDefinition, SkillRegistry


class StartupFundingAgent(BaseAgent):
    """Comprehensive startup funding guidance and investor matching agent."""

    role = "startup-funding"

    def __init__(self, provider_router: ProviderRouter, config: ArchonConfig) -> None:
        super().__init__(provider_router)
        self.config = config

    async def execute(self, context: dict[str, Any]) -> str:
        stage = context.get("startup_stage", "seed")
        sector = context.get("sector", "technology")
        revenue = context.get("current_revenue", "pre-revenue")
        location = context.get("location", "India")
        funding_amount = context.get("funding_amount", "not specified")
        team_size = context.get("team_size", "not specified")
        dpiit = context.get("dpiit_registered", "no")

        prompt = f"""Startup Funding & Investor Matching Assistant

Startup Profile:
- Stage: {stage} (idea/pre-seed/seed/series-a/series-b+)
- Sector: {sector}
- Revenue: ₹{revenue} annually
- Location: {location}
- Team Size: {team_size}
- Funding Needed: ₹{funding_amount}
- DPIIT Registered: {dpiit}

Provide COMPREHENSIVE funding guidance:

## 1. GOVERNMENT GRANTS & SCHEMES
- Startup India Seed Fund (₹20L-₹50L)
- DPIIT Recognition benefits
- Atal Innovation Mission (AIM) grants
- NITI AYOG Atal Tinkering Labs
- BIRAC funding (biotech)
- MSME schemes applicable
- State-specific startup grants
- Smart City innovation funds
- STPI funding (IT startups)
- KVIC grants (rural startups)

## 2. ANGEL INVESTORS & NETWORKS
- Indian Angel Network (IAN)
- Mumbai Angels
- Chennai Angels
- Bangalore Angels
- Hyderabad Angels
- LetsVenture
- AngelList India
- Indian Startup Network
- TiE Angels
- Lead Angels Network
- Typical ticket size: ₹25L-₹2Cr

## 3. VENTURE CAPITAL (VC) FUNDS
- Seed-stage VCs (YourNest, Blume, India Quotient)
- Early-stage VCs (Accel, Sequoia, Matrix)
- Growth-stage VCs (Tiger, General Atlantic, Warburg)
- Sector-specific VCs (healthtech, fintech, agri)
- Typical ticket size: ₹5Cr-₹100Cr+

## 4. ALTERNATIVE FUNDING
- Crowdfunding (Ketto, Milaap, Fueladream)
- Revenue-based financing (Klub, RecurClub)
- Venture debt (InnoVen, Trifecta)
- P2P lending platforms
- Government bank loans (MUDRA, CGTMSE)
- SIDBI fund of funds
- NBFC startup loans

## 5. INCUBATORS & ACCELERATORS
- NASSCOM 10K Startups
- T-Hub (Telangana)
- IIT/IIM incubators
- Zone Startups
- Techstars India
- Y Combinator (global)
- 500 Startups (global)
- WeWork Labs
- Google for Startups
- Amazon Launchpad

## 6. APPLICATION GUIDANCE
- Pitch deck template (10-15 slides)
- Financial model requirements
- Legal documents checklist
- Due diligence preparation
- Valuation methods
- Term sheet negotiation tips
- Cap table management
- ESOP structuring

## 7. INVESTOR MATCHING
Based on the startup profile, recommend 5-10 specific investors/incubators
with:
- Investment thesis match
- Typical ticket size
- Sector focus
- Contact/application process
- Portfolio examples
- Success rate insights"""

        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
            system_prompt="""You are a startup funding expert for Indian entrepreneurs. Provide comprehensive, actionable funding guidance with specific investor recommendations.

Key knowledge areas:
- Indian startup ecosystem (funding landscape 2024-25)
- Government schemes (DPIIT, Startup India, BIRAC, AIM)
- Angel networks and VC landscape in India
- Pitch preparation and investor communication
- Legal aspects (term sheets, valuation, due diligence)
- Alternative funding models

Always include:
- Specific names and contact details where possible
- Eligibility criteria and application links
- Timeline expectations
- Common mistakes to avoid
- Success stories for motivation""",
        )
        return f"""🚀 Startup Funding Guide - {stage.upper()} Stage | {sector}

{response.text}

---
📊 QUICK REFERENCE:
🔗 Startup India: https://www.startupindia.gov.in
🔗 DPIIT Recognition: https://www.startupindia.gov.in/content/sih/en/government-schemes.html
🔗 SEBI AIF: https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doRecognisedFpi=yes
🔗 LetsVenture: https://www.letsventure.com
🔗 TracXn: https://www.tracxn.com

💰 FUNDING FUNNEL:
Idea → ₹5-25L (Grants/Bootstraps)
Pre-Seed → ₹25L-2Cr (Angels)
Seed → ₹2-10Cr (Seed VCs)
Series A → ₹10-50Cr (Growth VCs)
Series B+ → ₹50Cr+ (Late-stage VCs)

⚠️ IMPORTANT:
- Never share sensitive data before NDA
- Get legal counsel for term sheets
- Maintain clean financials from Day 1
- Focus on traction over valuation early"""


class StartupFundingRegistration:
    """Register startup funding skill."""

    @staticmethod
    def register(registry: SkillRegistry, config: ArchonConfig, provider_router: ProviderRouter) -> None:
        skill = SkillDefinition(
            name="startup-funding",
            description="Comprehensive startup funding guidance including government grants, angel investors, VCs, and incubators for Indian entrepreneurs.",
            trigger_patterns=[
                "startup funding",
                "seed funding",
                "angel investor",
                "venture capital",
                "vc funding",
                "grant.*startup",
                "pitch deck",
                "fundraising",
                "dpiit.*startup",
                "incubator.*accelerator",
                "raise.*money.*startup",
                "investor.*india.*startup",
            ],
            version="1.0.0",
            provider_preference="anthropic",
            cost_tier="standard",
            state="ACTIVE",
        )
        registry.register(skill)
