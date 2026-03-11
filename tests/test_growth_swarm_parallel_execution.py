"""Tests for parallelized Growth Swarm execution in the orchestrator."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from archon.agents.base_agent import AgentResult
from archon.config import ArchonConfig
from archon.core.growth_router import GrowthSwarm
from archon.core.orchestrator import Orchestrator


class _TierBarrier:
    """Barrier that deadlocks under sequential execution."""

    def __init__(self, total: int) -> None:
        self._total = int(total)
        self._arrived = 0
        self._released = asyncio.Event()
        self._lock = asyncio.Lock()

    async def arrive_and_wait(self) -> None:
        async with self._lock:
            self._arrived += 1
            if self._arrived >= self._total:
                self._released.set()
        await self._released.wait()


@dataclass
class _StubAgent:
    name: str
    role: str = "fast"
    output: str = ""
    confidence: int = 50
    barrier: _TierBarrier | None = None
    require_keys: tuple[str, ...] = ()
    fail: bool = False

    async def run(self, goal: str, context: dict[str, Any], task_id: str) -> AgentResult:
        del goal, task_id
        if self.fail:
            raise RuntimeError("boom")
        if self.barrier is not None:
            await self.barrier.arrive_and_wait()
        for key in self.require_keys:
            assert key in context
            assert context[key] is not None
        return AgentResult(
            agent=self.name,
            role=self.role,
            output=self.output,
            confidence=self.confidence,
            metadata={"actions": []},
        )


def test_growth_swarm_tier1_runs_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = Orchestrator(ArchonConfig(), live_provider_calls=False)
    task_id = "task-growth-parallel"
    orchestrator.cost_governor.start_task(task_id)

    barrier = _TierBarrier(total=4)
    swarm = GrowthSwarm(
        prospector=_StubAgent("ProspectorAgent", output="leads", barrier=barrier),
        icp=_StubAgent("ICPAgent", role="primary", output="icp", barrier=barrier),
        outreach=_StubAgent(
            "OutreachAgent",
            role="coding",
            output="sequences",
            require_keys=("leads", "icp_profile"),
        ),
        nurture=_StubAgent(
            "NurtureAgent",
            output="nurture",
            require_keys=("outreach_sequences",),
        ),
        revenue_intel=_StubAgent(
            "RevenueIntelAgent", role="primary", output="signals", barrier=barrier
        ),
        partner=_StubAgent("PartnerAgent", output="partners", barrier=barrier),
        churn_defense=_StubAgent(
            "ChurnDefenseAgent",
            output="retention",
            require_keys=("revenue_signals",),
        ),
    )

    monkeypatch.setattr(orchestrator.growth_router, "build_growth_swarm", lambda: swarm)

    async def _run() -> dict[str, Any]:
        return await asyncio.wait_for(
            orchestrator._run_growth_swarm(goal="Grow pipeline", task_id=task_id, context={}),
            timeout=2.0,
        )

    try:
        output = asyncio.run(_run())
    finally:
        asyncio.run(orchestrator.aclose())

    reports = output["payload"]["agent_reports"]
    assert [report["agent"] for report in reports] == [
        "ProspectorAgent",
        "ICPAgent",
        "OutreachAgent",
        "NurtureAgent",
        "RevenueIntelAgent",
        "PartnerAgent",
        "ChurnDefenseAgent",
    ]
    for report in reports:
        assert report["metadata"]["swarm_status"] in {"complete", "failed", "skipped"}


def test_growth_swarm_skips_dependents_when_upstream_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = Orchestrator(ArchonConfig(), live_provider_calls=False)
    task_id = "task-growth-skip"
    orchestrator.cost_governor.start_task(task_id)

    swarm = GrowthSwarm(
        prospector=_StubAgent("ProspectorAgent", fail=True),
        icp=_StubAgent("ICPAgent", role="primary", output="icp"),
        outreach=_StubAgent("OutreachAgent", role="coding", output="sequences"),
        nurture=_StubAgent("NurtureAgent", output="nurture"),
        revenue_intel=_StubAgent("RevenueIntelAgent", role="primary", output="signals"),
        partner=_StubAgent("PartnerAgent", output="partners"),
        churn_defense=_StubAgent("ChurnDefenseAgent", output="retention"),
    )

    monkeypatch.setattr(orchestrator.growth_router, "build_growth_swarm", lambda: swarm)

    async def _run() -> dict[str, Any]:
        return await asyncio.wait_for(
            orchestrator._run_growth_swarm(goal="Grow pipeline", task_id=task_id, context={}),
            timeout=2.0,
        )

    try:
        output = asyncio.run(_run())
    finally:
        asyncio.run(orchestrator.aclose())

    by_agent = {report["agent"]: report for report in output["payload"]["agent_reports"]}
    assert by_agent["ProspectorAgent"]["metadata"]["swarm_status"] == "failed"
    assert by_agent["OutreachAgent"]["metadata"]["swarm_status"] == "skipped"
    assert by_agent["NurtureAgent"]["metadata"]["swarm_status"] == "skipped"
    assert by_agent["ChurnDefenseAgent"]["metadata"]["swarm_status"] == "complete"
