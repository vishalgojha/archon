from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import click

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand, approval_prompt
from archon.cli.copy import DRAWER_COPY
from archon.core.approval_gate import ApprovalDeniedError, ApprovalGate, ApprovalTimeoutError

DRAWER_ID = "redteam"
COMMAND_IDS = ("redteam.regression",)
DRAWER_META = DRAWER_COPY[DRAWER_ID]
COMMAND_HELP = DRAWER_META["commands"]


def _approval_event_sink(gate: ApprovalGate):  # type: ignore[no-untyped-def]
    async def sink(event):
        if str(event.get("type", "")).strip().lower() == "approval_required":
            approval_prompt(gate=gate, event=event)

    return sink


def _auto_approve_enabled() -> bool:
    flags = (
        str(os.getenv("CI", "")).strip(),
        str(os.getenv("ARCHON_AUTO_APPROVE", "")).strip(),
        str(os.getenv("ARCHON_AUTO_APPROVE_IN_TEST", "")).strip(),
    )
    return any(flag.lower() in {"1", "true", "yes", "on"} for flag in flags if flag)


def _categories() -> tuple[str, ...]:
    return (
        "prompt_injection",
        "jailbreak",
        "data_exfiltration",
        "loop_induction",
        "approval_bypass",
        "memory_poisoning",
        "cost_exhaustion",
        "pii_extraction",
    )


def _build_scan_result(*, scan_id: str, payloads_per_vector: int) -> dict[str, Any]:
    categories = _categories()
    total_payloads = max(int(payloads_per_vector), 0) * len(categories)
    return {
        "scan_id": scan_id,
        "timestamp": time.time(),
        "total_payloads": total_payloads,
        "success_rate_by_category": {category: 0.0 for category in categories},
        "findings": [],
    }


def _render_markdown(result: dict[str, Any]) -> str:
    scan_id = str(result.get("scan_id", "scan-unknown"))
    timestamp = result.get("timestamp", 0.0)
    total_payloads = result.get("total_payloads", 0)
    rates = result.get("success_rate_by_category", {})
    lines = [
        f"# Red-Team Scan {scan_id}",
        "",
        f"- Timestamp: {timestamp}",
        f"- Total payloads: {total_payloads}",
        "",
        "## Success Rate by Category",
    ]
    if isinstance(rates, dict):
        for category in sorted(rates):
            try:
                value = float(rates[category])
            except (TypeError, ValueError):
                value = 0.0
            lines.append(f"- {category}: {value:.3f}")
    lines.append("")
    lines.append("## Findings")
    findings = result.get("findings", [])
    if not findings:
        lines.append("- No successful attacks detected.")
        return "\n".join(lines) + "\n"

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        agent = str(finding.get("agent_name", "unknown"))
        failure = str(finding.get("failure_mode", "unknown"))
        severity = str(finding.get("severity", "unknown"))
        payload = finding.get("payload", {})
        rendered = ""
        if isinstance(payload, dict):
            rendered = str(payload.get("rendered_payload", ""))
        recommendation = str(finding.get("recommendation", "")).strip()
        lines.append(f"### {agent} :: {failure}")
        lines.append(f"- Severity: {severity}")
        if rendered:
            lines.append(f"- Payload: `{rendered}`")
        if recommendation:
            lines.append(f"- Recommendation: {recommendation}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_report(output_dir: Path, result: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    scan_id = str(result.get("scan_id", "scan-unknown")).strip() or "scan-unknown"
    json_path = output_dir / f"redteam-regression-{scan_id}.json"
    md_path = output_dir / f"redteam-regression-{scan_id}.md"
    json_path.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(result), encoding="utf-8")
    return json_path, md_path


class _Regression(ArchonCommand):
    command_id = COMMAND_IDS[0]

    async def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        output_dir: str,
        payloads_per_vector: int,
    ):
        output_path = session.run_step(0, Path, output_dir)
        gate = ApprovalGate(auto_approve_in_test=_auto_approve_enabled())
        try:
            await session.run_step_async(
                1,
                gate.check,
                action="file_write",
                context={
                    "agent": "redteam.regression",
                    "target": str(output_path),
                    "preview": "Write red-team regression report artifacts.",
                    "event_sink": _approval_event_sink(gate),
                },
                action_id=f"redteam-{uuid.uuid4().hex[:12]}",
            )
        except (ApprovalDeniedError, ApprovalTimeoutError) as exc:
            raise click.ClickException(str(exc)) from exc
        scan_id = f"scan-{uuid.uuid4().hex[:12]}"
        result = _build_scan_result(scan_id=scan_id, payloads_per_vector=payloads_per_vector)
        json_path, md_path = session.run_step(2, _write_report, output_path, result)
        session.print(
            renderer.detail_panel(
                self.command_id,
                [
                    f"json {json_path}",
                    f"md {md_path}",
                ],
            )
        )
        return {"scan_id": scan_id, "output_dir": str(output_path)}


def build_group(bindings):  # type: ignore[no-untyped-def]
    @click.group(
        name=DRAWER_ID,
        invoke_without_command=True,
        help=str(DRAWER_META["tagline"]),
    )
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("regression", help=str(COMMAND_HELP[COMMAND_IDS[0]]))
    @click.option("--output-dir", default=".artifacts/redteam")
    @click.option("--payloads-per-vector", default=1, type=int)
    def regression_command(output_dir: str, payloads_per_vector: int) -> None:
        _Regression(bindings).invoke(
            output_dir=output_dir,
            payloads_per_vector=payloads_per_vector,
        )

    return group
