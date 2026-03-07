"""Tests for automated red-team regression exports and failure thresholds."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from archon.redteam.adversarial import AdversarialPayload, AttackVector
from archon.redteam.regression import RegressionRunner, RegressionThresholds
from archon.redteam.scanner import Finding, ScanReport


def _payload(category: str, severity: str) -> AdversarialPayload:
    vector = AttackVector(
        vector_id=f"vec-{category}",
        category=category,
        description="desc",
        payload_template="template",
        severity=severity,
    )
    return AdversarialPayload(
        payload_id=f"payload-{category}",
        vector=vector,
        rendered_payload="payload",
        target_agent="agent-a",
    )


class _StubScanner:
    def __init__(self, report: ScanReport) -> None:
        self.report = report
        self.last_registry = {}

    async def scan(self, agent_registry, payloads_per_vector: int = 1):  # type: ignore[no-untyped-def]
        assert payloads_per_vector == 1
        self.last_registry = dict(agent_registry)
        return self.report

    def export_report(self, scan_report: ScanReport, path: str | Path) -> None:
        Path(path).write_text(f"# {scan_report.scan_id}\n", encoding="utf-8")


def test_regression_runner_exports_markdown_and_json() -> None:
    tmp_path = _tmp_dir("pass")
    report = ScanReport(
        scan_id="scan-pass",
        timestamp=1.0,
        findings=[],
        total_payloads=8,
        success_rate_by_category={"prompt_injection": 0.0},
    )
    runner = RegressionRunner(
        orchestrator=SimpleNamespace(provider_router=None),
        scanner=_StubScanner(report),  # type: ignore[arg-type]
    )

    outcome = asyncio.run(
        runner.run(
            output_dir=tmp_path,
            payloads_per_vector=1,
            agent_registry={"safe": lambda text: f"ok:{text}"},
        )
    )

    assert outcome.passed is True
    assert outcome.markdown_path.exists()
    assert outcome.json_path.exists()
    payload = json.loads(outcome.json_path.read_text(encoding="utf-8"))
    assert payload["scan_id"] == "scan-pass"
    assert payload["findings"] == []


def test_regression_runner_fails_on_blocking_findings_and_success_rate() -> None:
    tmp_path = _tmp_dir("fail")
    finding = Finding(
        agent_name="agent-a",
        payload=_payload("approval_bypass", "critical"),
        failure_mode="approval_bypass",
        severity="critical",
        recommendation="gate it",
    )
    report = ScanReport(
        scan_id="scan-fail",
        timestamp=2.0,
        findings=[finding],
        total_payloads=8,
        success_rate_by_category={"approval_bypass": 0.25},
    )
    runner = RegressionRunner(
        orchestrator=SimpleNamespace(provider_router=None),
        scanner=_StubScanner(report),  # type: ignore[arg-type]
        thresholds=RegressionThresholds(max_success_rate=0.0),
    )

    outcome = asyncio.run(
        runner.run(
            output_dir=tmp_path,
            payloads_per_vector=1,
            agent_registry={"unsafe": lambda text: f"unsafe:{text}"},
        )
    )

    assert outcome.passed is False
    assert outcome.blocking_findings
    assert outcome.failed_categories == {"approval_bypass": 0.25}


def _tmp_dir(label: str) -> Path:
    folder = Path("archon/tests/_tmp_redteam") / f"{label}-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder
