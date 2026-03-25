"""Tool registry for Indian SMB skill tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from archon.skills.skill_executor import SkillExecutor
from archon.swarm.tools.base import BaseSMBTool, ToolResult


@dataclass(slots=True)
class SkillTool(BaseSMBTool):
    name: str
    description: str
    executor: SkillExecutor

    async def execute(self, query: str, context: dict[str, Any]) -> ToolResult:
        try:
            answer = await self.executor.execute_skill(self.name, query, context)
            return ToolResult(
                answer=answer,
                confidence=0.7,
                sources=[],
                follow_up_needed=False,
            )
        except Exception as exc:
            return ToolResult(
                answer=f"Skill failed: {exc}",
                confidence=0.0,
                sources=[],
                follow_up_needed=True,
            )


class ToolRegistry:
    def __init__(self, executor: SkillExecutor) -> None:
        self.executor = executor
        self._tools = _build_tools(executor)

    def list_tools(self) -> dict[str, BaseSMBTool]:
        return dict(self._tools)

    def get_tool(self, name: str) -> BaseSMBTool | None:
        return self._tools.get(name)


SKILL_DESCRIPTIONS = {
    "gst-compliance": "GST filing, returns, compliance guidance.",
    "msme-loan-assistant": "MSME loan programs and eligibility.",
    "upi-fraud-detection": "UPI fraud detection and resolution steps.",
    "legal-aid": "Consumer court, RTI, and legal aid support.",
    "ondc-seller-assistant": "ONDC seller onboarding and operations.",
    "startup-india": "Startup India registration and benefits.",
    "kisan-advisory": "Crop, soil, and farmer advisories.",
    "healthcare-triage": "Healthcare triage and guidance.",
    "insurance-advisor": "Insurance schemes and recommendations.",
    "customs-import": "Customs import compliance.",
    "export-compliance": "Export compliance steps.",
    "fssai-compliance": "FSSAI licensing and compliance.",
    "govt-form-assistant": "Government form filling assistance.",
    "scholarship-application": "Scholarship eligibility and application help.",
    "solar-adoption": "Solar adoption planning and incentives.",
    "telecom-assistant": "Telecom plans, billing, porting support.",
    "vehicle-rto": "Vehicle RTO documentation and services.",
    "water-utility": "Water/sewer/electricity utility processes.",
    "property-verification": "Property verification checks.",
}


def _build_tools(executor: SkillExecutor) -> dict[str, BaseSMBTool]:
    tools: dict[str, BaseSMBTool] = {}
    for name, description in SKILL_DESCRIPTIONS.items():
        tools[name] = SkillTool(name=name, description=description, executor=executor)
    return tools
