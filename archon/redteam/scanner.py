"""Red-team vulnerability scanner across registered agents."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from archon.providers import ProviderRouter
from archon.redteam.adversarial import ATTACK_CATEGORIES, AdversarialPayload, RedTeamer, TrialResult


@dataclass(slots=True, frozen=True)
class Finding:
    agent_name: str
    payload: AdversarialPayload
    failure_mode: str
    severity: str
    recommendation: str


@dataclass(slots=True, frozen=True)
class ScanReport:
    scan_id: str
    timestamp: float
    findings: list[Finding]
    total_payloads: int
    success_rate_by_category: dict[str, float] = field(default_factory=dict)


class VulnerabilityScanner:
    """Runs full adversarial sweeps and summarizes vulnerability findings."""

    def __init__(
        self,
        *,
        redteamer: RedTeamer | None = None,
        router: ProviderRouter | None = None,
        llm_role: str = "fast",
    ) -> None:
        self.redteamer = redteamer or RedTeamer(router=router, llm_role=llm_role)
        self.router = router
        self.llm_role = llm_role

    async def scan(
        self,
        agent_registry: dict[str, Callable[[str], Awaitable[Any] | Any]]
        | list[tuple[str, Callable[[str], Awaitable[Any] | Any]]],
        payloads_per_vector: int = 5,
    ) -> ScanReport:
        """Run sweep for each agent and return one aggregate report."""

        if isinstance(agent_registry, dict):
            entries = list(agent_registry.items())
        else:
            entries = list(agent_registry)

        findings: list[Finding] = []
        total_payloads = 0
        category_total = {category: 0 for category in ATTACK_CATEGORIES}
        category_success = {category: 0 for category in ATTACK_CATEGORIES}

        per_agent_count = max(1, int(payloads_per_vector)) * len(ATTACK_CATEGORIES)
        for agent_name, agent_fn in entries:
            payloads = self.redteamer.generate_payloads(agent_name, count=per_agent_count)
            for payload in payloads:
                trial = await self.redteamer.run_trial(payload, agent_fn)
                total_payloads += 1
                category_total[payload.vector.category] += 1
                if trial.succeeded:
                    category_success[payload.vector.category] += 1
                    findings.append(
                        Finding(
                            agent_name=str(agent_name),
                            payload=payload,
                            failure_mode=trial.failure_mode,
                            severity=trial.severity,
                            recommendation=await self._recommendation_for(str(agent_name), trial),
                        )
                    )

        rates: dict[str, float] = {}
        for category in ATTACK_CATEGORIES:
            total = category_total[category]
            rates[category] = (category_success[category] / float(total)) if total else 0.0

        findings.sort(
            key=lambda row: (_severity_rank(row.severity), row.agent_name, row.failure_mode)
        )
        return ScanReport(
            scan_id=f"scan-{uuid.uuid4().hex[:12]}",
            timestamp=time.time(),
            findings=findings,
            total_payloads=total_payloads,
            success_rate_by_category=rates,
        )

    def export_report(self, scan_report: ScanReport, path: str | Path) -> None:
        """Export scan findings to markdown."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            f"# Red-Team Scan {scan_report.scan_id}",
            "",
            f"- Timestamp: {scan_report.timestamp}",
            f"- Total payloads: {scan_report.total_payloads}",
            "",
            "## Success Rate by Category",
        ]
        for category, value in sorted(scan_report.success_rate_by_category.items()):
            lines.append(f"- {category}: {value:.3f}")

        lines.extend(["", "## Findings"])
        if not scan_report.findings:
            lines.append("- No successful attacks detected.")
        else:
            for finding in scan_report.findings:
                lines.extend(
                    [
                        f"### {finding.agent_name} :: {finding.failure_mode}",
                        f"- Severity: {finding.severity}",
                        f"- Payload: `{finding.payload.rendered_payload}`",
                        f"- Recommendation: {finding.recommendation}",
                        "",
                    ]
                )

        target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    async def _recommendation_for(self, agent_name: str, trial: TrialResult) -> str:
        if self.router is not None:
            try:
                response = await self.router.invoke(
                    role=self.llm_role,
                    prompt=(
                        "Provide one concise defensive recommendation for this finding.\n"
                        f"Agent: {agent_name}\n"
                        f"Failure mode: {trial.failure_mode}\n"
                        f"Output: {trial.output}"
                    ),
                    system_prompt="Return one actionable hardening recommendation only.",
                )
                text = str(getattr(response, "text", "") or "").strip()
                if text:
                    return text
            except Exception:
                pass

        defaults = {
            "prompt_injection": "Add input sanitization and strict system prompt boundaries.",
            "approval_bypass": "Gate all external actions with ApprovalGate checks.",
            "cost_exhaustion": "Add token budget checks before expensive model calls.",
            "data_exfiltration": "Mask secrets and enforce data-leak prevention filters.",
        }
        return defaults.get(
            trial.failure_mode, "Add input validation and policy checks for this path."
        )


def _severity_rank(severity: str) -> int:
    mapping = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return mapping.get(str(severity).lower(), 4)
