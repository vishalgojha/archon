"""Finance CFO domain agent for ARCHON."""

from __future__ import annotations

from typing import Any

from archon.agents.base_agent import AgentResult, BaseAgent

SYSTEM_PROMPT = """
You are ARCHON's Finance and CFO agent, built for Indian SMB finance teams, CFOs, and CAs.

Your job is to convert raw financial data into board-ready intelligence and operational
clarity — fast.

Outcomes you produce:
- MIS report generation from P&L, balance sheet, and cash flow inputs
- GST reconciliation summaries and filing readiness checks
- Cash runway analysis with scenario modelling (best / base / worst)
- Budget vs actuals variance commentary
- Investor-ready financial narrative drafts
- Vendor payment priority ranking by cash position

Always work with INR. Reference Indian accounting standards (Ind AS) where relevant.
Never invent numbers — derive only from context provided.
Flag data gaps explicitly. Output structured JSON with narrative summary section.
"""


class FinanceCFOAgent(BaseAgent):
    """Finance and CFO intelligence for Indian SMBs.

    Example:
        >>> result = await agent.run("Generate MIS", {}, "task-1")
        >>> result.role
        'primary'
    """

    role = "primary"

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        """Run a finance/CFO domain task.

        Example:
            >>> result = await agent.run("Cash runway", {"currency": "INR"}, "task-1")
            >>> result.metadata["sector"]
            'finance_cfo'
        """

        prompt = f"Goal: {goal}\nContext: {context}\n{SYSTEM_PROMPT}"
        response = await self.ask_model(
            prompt,
            task_id=task_id,
            system_prompt=SYSTEM_PROMPT,
        )
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=response.text,
            confidence=85,
            metadata={
                "provider": response.provider,
                "model": response.model,
                "cost_usd": response.usage.cost_usd,
                "sector": "finance_cfo",
            },
        )
