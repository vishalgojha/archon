"""Tests for workflow evolution engine, A/B tester, and immutable audit trail."""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from archon.evolution.ab_tester import ABTester, SyntheticTask
from archon.evolution.audit_trail import AuditEntry, ImmutableAuditTrail
from archon.evolution.engine import (
    DEFAULT_KNOWN_AGENTS,
    OptimizationResult,
    SelfEvolutionEngine,
    Step,
    WorkflowDefinition,
)


def _workflow(
    workflow_id: str, *, version: int = 1, agent: str = "researcher"
) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id=workflow_id,
        name=f"Workflow {workflow_id}",
        steps=[
            Step(step_id="s1", agent=agent, action="analyze", config={}, dependencies=[]),
            Step(
                step_id="s2",
                agent="synthesizer",
                action="summarize",
                config={},
                dependencies=["s1"],
            ),
        ],
        metadata={"owner": "test"},
        version=version,
        created_at=1.0,
    )


def _tmp_dir(name: str) -> Path:
    path = Path("archon/tests") / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_workflow_definition_validation_circular_and_missing_agent() -> None:
    circular = WorkflowDefinition(
        workflow_id="wf-circular",
        name="Circular",
        steps=[
            Step(step_id="a", agent="researcher", action="x", config={}, dependencies=["b"]),
            Step(step_id="b", agent="synthesizer", action="y", config={}, dependencies=["a"]),
        ],
        metadata={},
        version=1,
        created_at=1.0,
    )
    with pytest.raises(ValueError, match="Circular dependency"):
        circular.validate(DEFAULT_KNOWN_AGENTS)

    missing_agent = _workflow("wf-missing-agent", agent="unknown_agent")
    with pytest.raises(ValueError, match="Unknown agent"):
        missing_agent.validate(DEFAULT_KNOWN_AGENTS)


class _FakeOrchestrator:
    def __init__(self, proposal_text: str) -> None:
        self.proposal_text = proposal_text
        self.calls: list[dict[str, object]] = []

    async def execute(self, *, goal: str, mode: str = "debate", **kwargs) -> SimpleNamespace:
        self.calls.append({"goal": goal, "mode": mode, "kwargs": kwargs})
        return SimpleNamespace(final_answer=self.proposal_text)


@pytest.mark.asyncio
async def test_self_evolution_engine_optimize_stage_and_rollback() -> None:
    tmp_dir = _tmp_dir("_tmp_evolution_engine")
    audit = ImmutableAuditTrail(str(tmp_dir / "audit.sqlite3"))
    proposal = json.dumps(
        {
            "name": "Workflow wf-1 improved",
            "steps": [
                {
                    "step_id": "s1",
                    "agent": "researcher",
                    "action": "analyze",
                    "config": {"depth": "deep"},
                    "dependencies": [],
                },
                {
                    "step_id": "s2",
                    "agent": "synthesizer",
                    "action": "summarize",
                    "config": {},
                    "dependencies": ["s1"],
                },
            ],
            "improvement_rationale": "Increase analysis depth before synthesis.",
        }
    )
    orchestrator = _FakeOrchestrator(proposal)
    engine = SelfEvolutionEngine(orchestrator, audit_trail=audit)

    original = _workflow("wf-1", version=1)
    engine.create_workflow(original)
    optimization = await engine.optimize("wf-1")

    assert orchestrator.calls
    assert orchestrator.calls[0]["mode"] == "debate"
    assert optimization.original.version == 1
    assert optimization.candidate.version == 2

    staged = engine.stage(optimization)
    assert staged.status == "pending_ab_test"
    assert engine.get_staged_workflow("wf-1") is not None

    # Simulate promoted candidate becoming active before rollback.
    engine._workflows["wf-1"] = optimization.candidate  # noqa: SLF001
    restored = engine.rollback("wf-1")
    assert restored.version == 1
    assert engine.get_workflow("wf-1").version == 1
    assert any(entry.event_type == "workflow_rolled_back" for entry in audit.get_history("wf-1"))
    audit.close()


def test_self_evolution_engine_rejects_invalid_stage() -> None:
    tmp_dir = _tmp_dir("_tmp_evolution_stage")
    audit = ImmutableAuditTrail(str(tmp_dir / "audit.sqlite3"))
    engine = SelfEvolutionEngine(_FakeOrchestrator("{}"), audit_trail=audit)

    original = _workflow("wf-stage", version=1)
    engine.create_workflow(original)
    invalid_candidate = WorkflowDefinition(
        workflow_id="wf-stage",
        name="Invalid",
        steps=[Step(step_id="s1", agent="ghost_agent", action="noop", config={}, dependencies=[])],
        metadata={},
        version=2,
        created_at=2.0,
    )
    with pytest.raises(ValueError, match="Unknown agent"):
        engine.stage(
            OptimizationResult(
                original=original,
                candidate=invalid_candidate,
                improvement_rationale="invalid",
            )
        )
    audit.close()


def test_ab_tester_composite_score_formula() -> None:
    score = ABTester.calculate_composite_score(
        correctness=0.8,
        latency_ms=50.0,
        cost_usd=0.2,
        max_latency_ms=100.0,
        max_cost_usd=0.5,
    )
    assert score == pytest.approx(0.7, abs=1e-6)


@pytest.mark.asyncio
async def test_ab_tester_winner_and_concurrency() -> None:
    workflow_a = _workflow("wf-a")
    workflow_b = _workflow("wf-b")
    tasks = [
        SyntheticTask(
            task_id=f"task-{index}",
            description=f"Synthetic task {index}",
            expected_output_schema={"answer": "str"},
            difficulty="medium",
        )
        for index in range(4)
    ]

    running = {"wf-a": 0, "wf-b": 0}
    max_running = {"wf-a": 0, "wf-b": 0}
    events: list[tuple[str, str, float]] = []

    async def executor(workflow: WorkflowDefinition, task: SyntheticTask) -> dict[str, object]:
        del task
        wid = workflow.workflow_id
        running[wid] += 1
        max_running[wid] = max(max_running[wid], running[wid])
        events.append((wid, "start", time.perf_counter()))
        await asyncio.sleep(0.025)
        events.append((wid, "end", time.perf_counter()))
        running[wid] -= 1
        quality = "high" if wid == "wf-b" else "medium"
        return {
            "output": {"answer": "ok", "quality": quality},
            "latency_ms": 22.0 if wid == "wf-b" else 32.0,
            "cost_usd": 0.04 if wid == "wf-b" else 0.08,
        }

    async def judge(task: SyntheticTask, output: object) -> float:
        del task
        if isinstance(output, dict) and output.get("quality") == "high":
            return 0.98
        return 0.7

    tester = ABTester(executor=executor, correctness_judge=judge)
    trial = await tester.run_trial(workflow_a, workflow_b, tasks)

    assert trial.recommended_winner == "wf-b"
    assert trial.aggregate_scores["wf-b"] > trial.aggregate_scores["wf-a"]
    assert len(trial.workflow_a_results) == len(tasks)
    assert len(trial.workflow_b_results) == len(tasks)
    assert max_running["wf-a"] > 1
    assert max_running["wf-b"] > 1

    first_b_start = min(ts for wid, phase, ts in events if wid == "wf-b" and phase == "start")
    last_a_end = max(ts for wid, phase, ts in events if wid == "wf-a" and phase == "end")
    assert first_b_start >= last_a_end


def test_immutable_audit_trail_append_verify_history_and_export() -> None:
    tmp_dir = _tmp_dir("_tmp_evolution_audit")
    audit = ImmutableAuditTrail(str(tmp_dir / "audit.sqlite3"))

    entry_1 = audit.append(
        AuditEntry(
            entry_id="e1",
            timestamp=1.0,
            event_type="workflow_created",
            workflow_id="wf-1",
            actor="tester",
            payload={"version": 1},
            prev_hash="",
            entry_hash="",
        )
    )
    entry_2 = audit.append(
        AuditEntry(
            entry_id="e2",
            timestamp=2.0,
            event_type="workflow_staged",
            workflow_id="wf-2",
            actor="tester",
            payload={"version": 2},
            prev_hash="",
            entry_hash="",
        )
    )
    entry_3 = audit.append(
        AuditEntry(
            entry_id="e3",
            timestamp=3.0,
            event_type="workflow_rolled_back",
            workflow_id="wf-1",
            actor="tester",
            payload={"version": 1, "reason": "regression"},
            prev_hash="",
            entry_hash="",
        )
    )

    assert entry_1.entry_hash
    assert entry_2.prev_hash == entry_1.entry_hash
    assert entry_3.prev_hash == entry_2.entry_hash
    assert audit.verify_integrity() is True

    wf1_history = audit.get_history("wf-1")
    assert [row.entry_id for row in wf1_history] == ["e1", "e3"]

    export_path = audit.export_chain(tmp_dir / "chain.jsonl")
    lines = export_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3

    with sqlite3.connect(audit.db_path) as conn:
        conn.execute(
            "UPDATE audit_entries SET payload_json = ? WHERE entry_id = ?",
            ('{"tampered":true}', "e2"),
        )
        conn.commit()

    assert audit.verify_integrity() is False
    audit.close()
