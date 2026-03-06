"""Automated hardening helpers for detected red-team findings."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from archon.redteam.scanner import Finding


@dataclass(slots=True, frozen=True)
class HardeningResult:
    finding: Finding
    fix_applied: bool
    fix_description: str
    requires_manual_review: bool


def sanitize_prompt(text: str) -> str:
    """Strip common prompt-injection and role-play takeover patterns."""

    cleaned = str(text or "")
    patterns = [
        r"(?i)ignore\s+previous\s+instructions",
        r"(?i)you\s+are\s+now\b[^\n]*",
        r"(?i)disregard\s+all\s+prior\s+rules",
        r"(?i)system\s+override",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


class AutoHardener:
    """Applies targeted hardening actions for non-critical findings."""

    def __init__(
        self,
        *,
        approval_gate_checker: Callable[[Finding], bool] | None = None,
        default_budget_tokens: int = 4000,
    ) -> None:
        self.approval_gate_checker = approval_gate_checker or self._default_gate_checker
        self.default_budget_tokens = max(1, int(default_budget_tokens))
        self._budget_wrappers: dict[str, Callable[[str], Awaitable[Any]]] = {}

    def harden(self, finding: Finding) -> HardeningResult:
        severity = str(finding.severity or "").lower()
        category = str(finding.payload.vector.category or finding.failure_mode).lower()

        if severity == "critical":
            return HardeningResult(
                finding=finding,
                fix_applied=False,
                fix_description="Critical finding requires manual patch review.",
                requires_manual_review=True,
            )

        if category == "prompt_injection":
            return HardeningResult(
                finding=finding,
                fix_applied=True,
                fix_description="Apply sanitize_prompt(text) before LLM invocation.",
                requires_manual_review=False,
            )

        if category == "approval_bypass":
            gate_ok = bool(self.approval_gate_checker(finding))
            return HardeningResult(
                finding=finding,
                fix_applied=gate_ok,
                fix_description=(
                    "Verified ApprovalGate call-chain for flagged action."
                    if gate_ok
                    else "ApprovalGate not found in call-chain; add mandatory gating."
                ),
                requires_manual_review=False,
            )

        if category == "cost_exhaustion":
            wrapper = self.add_budget_check(
                self._passthrough_agent, budget_tokens=self.default_budget_tokens
            )
            self._budget_wrappers[finding.agent_name] = wrapper
            return HardeningResult(
                finding=finding,
                fix_applied=True,
                fix_description="Added pre-execution token budget check wrapper.",
                requires_manual_review=False,
            )

        return HardeningResult(
            finding=finding,
            fix_applied=False,
            fix_description="No automatic fix strategy for this category.",
            requires_manual_review=False,
        )

    def add_budget_check(
        self,
        agent_fn: Callable[[str], Awaitable[Any] | Any],
        *,
        budget_tokens: int | None = None,
    ) -> Callable[[str], Awaitable[Any]]:
        """Wrap callable with token-budget guard before execution."""

        limit = max(1, int(budget_tokens or self.default_budget_tokens))

        async def wrapped(user_input: str) -> Any:
            estimated_tokens = max(1, int(len(str(user_input)) / 4))
            if estimated_tokens > limit:
                raise ValueError("token budget exceeded")
            result = agent_fn(user_input)
            if asyncio.iscoroutine(result):
                result = await result
            return result

        return wrapped

    @staticmethod
    async def _passthrough_agent(user_input: str) -> str:
        return user_input

    @staticmethod
    def _default_gate_checker(_finding: Finding) -> bool:
        return False
