from __future__ import annotations

from archon.cli.drawers.evolve import _load_staged_workflows
from archon.evolution.audit_trail import ImmutableAuditTrail
from archon.evolution.engine import (
    OptimizationResult,
    SelfEvolutionEngine,
    Step,
    WorkflowDefinition,
)


def _workflow(workflow_id: str, *, version: int) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id=workflow_id,
        name=f"Workflow {workflow_id}",
        steps=[
            Step(step_id="s1", agent="researcher", action="analyze", config={}, dependencies=[]),
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


def test_load_staged_workflows_roundtrip() -> None:
    audit = ImmutableAuditTrail(":memory:")
    engine = SelfEvolutionEngine(object(), audit_trail=audit)

    original = _workflow("wf-1", version=1)
    candidate = _workflow("wf-1", version=2)
    engine.create_workflow(original)
    engine.stage(
        OptimizationResult(
            original=original,
            candidate=candidate,
            improvement_rationale="Improve the workflow.",
        )
    )

    staged, previous, rationale = _load_staged_workflows(audit, workflow_id="wf-1")

    assert staged.version == 2
    assert previous.version == 1
    assert rationale == "Improve the workflow."
    audit.close()
