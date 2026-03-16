"""Self-evolution workflow engine for proposal generation and staging."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from archon.evolution.audit_trail import AuditEntry, ImmutableAuditTrail

DEFAULT_KNOWN_AGENTS: frozenset[str] = frozenset(
    {
        "researcher",
        "critic",
        "devils_advocate",
        "fact_checker",
        "synthesizer",
        "ResearcherAgent",
        "CriticAgent",
        "DevilsAdvocateAgent",
        "FactCheckerAgent",
        "SynthesizerAgent",
    }
)


@dataclass(slots=True, frozen=True)
class Step:
    """Workflow execution step."""

    step_id: str
    agent: str
    action: str
    config: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class WorkflowDefinition:
    """Versioned workflow definition managed by self-evolution engine."""

    workflow_id: str
    name: str
    steps: list[Step]
    metadata: dict[str, Any]
    version: int
    created_at: float

    def validate(self, known_agents: set[str] | frozenset[str]) -> None:
        """Validate step topology and known-agent constraints."""

        step_map: dict[str, Step] = {}
        for step in self.steps:
            if step.step_id in step_map:
                raise ValueError(f"Duplicate step_id detected: {step.step_id}")
            step_map[step.step_id] = step
            if step.agent not in known_agents:
                raise ValueError(f"Unknown agent in workflow '{self.workflow_id}': {step.agent}")

        for step in self.steps:
            for dep in step.dependencies:
                if dep not in step_map:
                    raise ValueError(
                        f"Missing dependency '{dep}' in workflow '{self.workflow_id}'."
                    )

        visited: dict[str, int] = {}

        def dfs(step_id: str) -> None:
            state = visited.get(step_id, 0)
            if state == 1:
                raise ValueError(f"Circular dependency detected in workflow '{self.workflow_id}'.")
            if state == 2:
                return
            visited[step_id] = 1
            for dep in step_map[step_id].dependencies:
                dfs(dep)
            visited[step_id] = 2

        for step in self.steps:
            dfs(step.step_id)


@dataclass(slots=True, frozen=True)
class OptimizationResult:
    """Candidate optimization proposal output from debate mode."""

    original: WorkflowDefinition
    candidate: WorkflowDefinition
    improvement_rationale: str


@dataclass(slots=True, frozen=True)
class StagedWorkflow:
    """Workflow candidate staged for pending A/B evaluation."""

    workflow_id: str
    original_version: int
    candidate_version: int
    candidate: WorkflowDefinition
    status: str
    staged_at: float


class SelfEvolutionEngine:
    """Generates and stages workflow evolution proposals."""

    def __init__(
        self,
        orchestrator: Any,
        *,
        audit_trail: ImmutableAuditTrail | None = None,
        known_agents: set[str] | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.audit_trail = audit_trail or ImmutableAuditTrail(":memory:")
        self.known_agents: set[str] = set(known_agents or DEFAULT_KNOWN_AGENTS)
        self._workflows: dict[str, WorkflowDefinition] = {}
        self._staged: dict[str, StagedWorkflow] = {}

    def create_workflow(
        self, workflow: WorkflowDefinition, *, actor: str = "system"
    ) -> WorkflowDefinition:
        """Register a new workflow and emit audit event."""

        self.validate_workflow(workflow)
        self._workflows[workflow.workflow_id] = workflow
        self._append_event(
            event_type="workflow_created",
            workflow_id=workflow.workflow_id,
            actor=actor,
            payload={"workflow": _workflow_to_dict(workflow)},
        )
        return workflow

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition:
        """Return current active workflow definition."""

        workflow = self._workflows.get(workflow_id)
        if workflow is None:
            raise KeyError(f"Unknown workflow_id: {workflow_id}")
        return workflow

    def get_staged_workflow(self, workflow_id: str) -> StagedWorkflow | None:
        """Return currently staged candidate workflow, if present."""

        return self._staged.get(workflow_id)

    def validate_workflow(self, workflow: WorkflowDefinition) -> None:
        """Run structural validation for one workflow definition."""

        workflow.validate(self.known_agents)

    async def optimize(self, workflow_id: str) -> OptimizationResult:
        """Generate candidate workflow proposal via orchestrator debate mode."""

        original = self.get_workflow(workflow_id)
        proposal_prompt = (
            "Propose a JSON workflow optimization candidate.\n"
            "Return JSON object with optional keys: name, steps, metadata, improvement_rationale.\n"
            "Each step item shape: {step_id, agent, action, config, dependencies}.\n"
            f"Current workflow JSON:\n{json.dumps(_workflow_to_dict(original), separators=(',', ':'))}"
        )
        response = await self.orchestrator.execute(goal=proposal_prompt, mode="debate")
        response_text = str(getattr(response, "final_answer", response))
        proposal = _extract_json_object(response_text)

        candidate_name = str(proposal.get("name", original.name)) if proposal else original.name
        candidate_steps = (
            _steps_from_proposal(proposal.get("steps"), original.steps)
            if proposal
            else original.steps
        )
        candidate_metadata = dict(original.metadata)
        if proposal and isinstance(proposal.get("metadata"), dict):
            candidate_metadata.update(proposal["metadata"])
        candidate = WorkflowDefinition(
            workflow_id=original.workflow_id,
            name=candidate_name,
            steps=candidate_steps,
            metadata=candidate_metadata,
            version=original.version + 1,
            created_at=time.time(),
        )
        self.validate_workflow(candidate)
        rationale = (
            str(proposal.get("improvement_rationale", "")).strip()
            if proposal
            else response_text.strip()
        ) or "Debate-mode optimization proposal generated."
        return OptimizationResult(
            original=original, candidate=candidate, improvement_rationale=rationale
        )

    def stage(
        self, optimization_result: OptimizationResult, *, actor: str = "self_evolution_engine"
    ) -> StagedWorkflow:
        """Validate and stage candidate workflow for pending A/B test."""

        self.validate_workflow(optimization_result.candidate)
        if optimization_result.original.workflow_id != optimization_result.candidate.workflow_id:
            raise ValueError("Original and candidate workflow_id must match for staging.")

        staged = StagedWorkflow(
            workflow_id=optimization_result.candidate.workflow_id,
            original_version=optimization_result.original.version,
            candidate_version=optimization_result.candidate.version,
            candidate=optimization_result.candidate,
            status="pending_ab_test",
            staged_at=time.time(),
        )
        self._staged[staged.workflow_id] = staged
        self._append_event(
            event_type="workflow_staged",
            workflow_id=staged.workflow_id,
            actor=actor,
            payload={
                "previous_workflow": _workflow_to_dict(optimization_result.original),
                "candidate_workflow": _workflow_to_dict(optimization_result.candidate),
                "improvement_rationale": optimization_result.improvement_rationale,
            },
        )
        return staged

    def rollback(
        self, workflow_id: str, *, actor: str = "self_evolution_engine"
    ) -> WorkflowDefinition:
        """Restore previous workflow version from audit history."""

        history = self.audit_trail.get_history(workflow_id)
        for entry in reversed(history):
            for payload_key in ("previous_workflow", "restored_workflow", "workflow"):
                candidate_payload = entry.payload.get(payload_key)
                if isinstance(candidate_payload, dict):
                    restored = _workflow_from_dict(candidate_payload)
                    self.validate_workflow(restored)
                    self._workflows[workflow_id] = restored
                    self._staged.pop(workflow_id, None)
                    self._append_event(
                        event_type="workflow_rolled_back",
                        workflow_id=workflow_id,
                        actor=actor,
                        payload={
                            "source_entry_id": entry.entry_id,
                            "restored_workflow": _workflow_to_dict(restored),
                        },
                    )
                    return restored
        raise RuntimeError(
            f"No rollback target found in audit trail for workflow_id={workflow_id}."
        )

    def _append_event(
        self, *, event_type: str, workflow_id: str, actor: str, payload: dict[str, Any]
    ) -> AuditEntry:
        entry = AuditEntry(
            entry_id=f"audit-{uuid.uuid4().hex[:12]}",
            timestamp=time.time(),
            event_type=event_type,
            workflow_id=workflow_id,
            actor=actor,
            payload=payload,
            prev_hash="",
            entry_hash="",
        )
        return self.audit_trail.append(entry)


def _workflow_to_dict(workflow: WorkflowDefinition) -> dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "name": workflow.name,
        "steps": [
            {
                "step_id": step.step_id,
                "agent": step.agent,
                "action": step.action,
                "config": step.config,
                "dependencies": step.dependencies,
            }
            for step in workflow.steps
        ],
        "metadata": workflow.metadata,
        "version": workflow.version,
        "created_at": workflow.created_at,
    }


def _workflow_from_dict(data: dict[str, Any]) -> WorkflowDefinition:
    steps_raw = data.get("steps", [])
    steps = _steps_from_proposal(steps_raw, [])
    return WorkflowDefinition(
        workflow_id=str(data["workflow_id"]),
        name=str(data.get("name", data["workflow_id"])),
        steps=steps,
        metadata=dict(data.get("metadata", {})),
        version=int(data.get("version", 1)),
        created_at=float(data.get("created_at", time.time())),
    )


def _steps_from_proposal(raw_steps: Any, fallback: list[Step]) -> list[Step]:
    if not isinstance(raw_steps, list) or not raw_steps:
        return list(fallback)
    parsed_steps: list[Step] = []
    for index, row in enumerate(raw_steps):
        if not isinstance(row, dict):
            continue
        step_id = str(row.get("step_id") or f"step-{index + 1}")
        agent = str(row.get("agent", ""))
        action = str(row.get("action", ""))
        if not agent or not action:
            continue
        config = dict(row.get("config", {})) if isinstance(row.get("config"), dict) else {}
        dependencies_raw = row.get("dependencies", [])
        dependencies = (
            [str(dep) for dep in dependencies_raw] if isinstance(dependencies_raw, list) else []
        )
        parsed_steps.append(
            Step(
                step_id=step_id,
                agent=agent,
                action=action,
                config=config,
                dependencies=dependencies,
            )
        )
    return parsed_steps or list(fallback)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    body = text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        body = "\n".join(lines).strip()
    for candidate in (
        body,
        body[body.find("{") : body.rfind("}") + 1] if "{" in body and "}" in body else "",
    ):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None
