from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import click

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand, approval_prompt
from archon.cli.copy import DRAWER_COPY
from archon.core.approval_gate import ApprovalDeniedError, ApprovalGate, ApprovalTimeoutError
from archon.evolution.audit_trail import AuditEntry, ImmutableAuditTrail
from archon.evolution.engine import (
    SelfEvolutionEngine,
    WorkflowDefinition,
    _workflow_from_dict,
    _workflow_to_dict,
)
from archon.studio.store import StudioWorkflowStore

DRAWER_ID = "evolve"
COMMAND_IDS = ("evolve.plan", "evolve.apply")
DRAWER_META = DRAWER_COPY[DRAWER_ID]
COMMAND_HELP = DRAWER_META["commands"]


def _studio_store_path() -> str:
    return str(os.getenv("ARCHON_STUDIO_DB", "archon_studio.sqlite3"))


def _audit_trail_path() -> str:
    return "archon_evolution_audit.sqlite3"


def _load_workflow(
    store: StudioWorkflowStore,
    *,
    tenant_id: str,
    workflow_id: str,
) -> WorkflowDefinition:
    workflow = store.get(tenant_id, workflow_id)
    if workflow is None:
        raise click.ClickException(f"Workflow '{workflow_id}' not found for tenant '{tenant_id}'.")
    return workflow


def _latest_staged_payload(
    audit: ImmutableAuditTrail,
    *,
    workflow_id: str,
) -> dict[str, Any]:
    history = audit.get_history(workflow_id)
    for entry in reversed(history):
        if entry.event_type == "workflow_staged":
            return dict(entry.payload)
    raise click.ClickException(f"No staged candidate found for workflow '{workflow_id}'.")


def _load_staged_workflows(
    audit: ImmutableAuditTrail,
    *,
    workflow_id: str,
) -> tuple[WorkflowDefinition, WorkflowDefinition, str]:
    payload = _latest_staged_payload(audit, workflow_id=workflow_id)
    candidate_raw = payload.get("candidate_workflow")
    previous_raw = payload.get("previous_workflow")
    if not isinstance(candidate_raw, dict) or not isinstance(previous_raw, dict):
        raise click.ClickException("Staged workflow payload is missing required data.")
    rationale = str(payload.get("improvement_rationale", "") or "").strip()
    return _workflow_from_dict(candidate_raw), _workflow_from_dict(previous_raw), rationale


def _approval_event_sink(gate: ApprovalGate):  # type: ignore[no-untyped-def]
    async def sink(event):
        if str(event.get("type", "")).strip().lower() == "approval_required":
            approval_prompt(gate=gate, event=event)

    return sink


class _Plan(ArchonCommand):
    command_id = COMMAND_IDS[0]

    async def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        workflow_id: str,
        tenant_id: str,
        live_providers: bool,
        config_path: str,
    ):
        config = session.run_step(0, self.bindings._load_config, config_path)
        store = session.run_step(1, StudioWorkflowStore, _studio_store_path())
        workflow = session.run_step(
            2, _load_workflow, store, tenant_id=tenant_id, workflow_id=workflow_id
        )
        audit = session.run_step(3, ImmutableAuditTrail, _audit_trail_path())
        orchestrator = session.run_step(
            4,
            self.bindings.Orchestrator,
            config=config,
            live_provider_calls=live_providers,
        )
        engine = session.run_step(
            5,
            SelfEvolutionEngine,
            orchestrator,
            audit_trail=audit,
        )
        session.update_step(6, "running")
        try:
            engine.create_workflow(workflow, actor="evolve.plan")
            optimization = await engine.optimize(workflow.workflow_id)
            staged = engine.stage(optimization, actor="evolve.plan")
        finally:
            await orchestrator.aclose()
            audit.close()
        session.update_step(6, "success")
        payload = {
            "workflow_id": staged.workflow_id,
            "original_version": staged.original_version,
            "candidate_version": staged.candidate_version,
            "status": staged.status,
            "improvement_rationale": optimization.improvement_rationale,
            "candidate_workflow": _workflow_to_dict(optimization.candidate),
        }
        session.print(renderer.detail_panel(self.command_id, [json.dumps(payload, indent=2)]))
        return {
            "workflow_id": staged.workflow_id,
            "candidate_version": staged.candidate_version,
            "status": staged.status,
        }


class _Apply(ArchonCommand):
    command_id = COMMAND_IDS[1]

    async def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        workflow_id: str,
        tenant_id: str,
        config_path: str,
    ):
        session.run_step(0, self.bindings._load_config, config_path)
        store = session.run_step(1, StudioWorkflowStore, _studio_store_path())
        current = session.run_step(
            2, _load_workflow, store, tenant_id=tenant_id, workflow_id=workflow_id
        )
        audit = session.run_step(3, ImmutableAuditTrail, _audit_trail_path())
        candidate, previous, rationale = session.run_step(
            4, _load_staged_workflows, audit, workflow_id=workflow_id
        )
        gate = ApprovalGate(supervised_mode=True)
        session.update_step(5, "running")
        try:
            await gate.check(
                action="db_write",
                context={
                    "agent": "evolve.apply",
                    "target": workflow_id,
                    "preview": rationale or "Promote staged workflow candidate.",
                    "event_sink": _approval_event_sink(gate),
                },
                action_id=f"evolve-{uuid.uuid4().hex[:12]}",
            )
        except (ApprovalDeniedError, ApprovalTimeoutError):
            engine = SelfEvolutionEngine(object(), audit_trail=audit)
            restored = engine.rollback(workflow_id, actor="evolve.apply")
            store.save(tenant_id, restored, workflow_id=workflow_id)
            audit.close()
            session.update_step(5, "success")
            session.run_step(6, lambda: None)
            return {
                "result_key": "denied",
                "workflow_id": workflow_id,
                "restored_version": restored.version,
            }

        store.save(tenant_id, candidate, workflow_id=workflow_id)
        audit.append(
            AuditEntry(
                entry_id=f"audit-{uuid.uuid4().hex[:12]}",
                timestamp=time.time(),
                event_type="workflow_promoted",
                workflow_id=workflow_id,
                actor="evolve.apply",
                payload={
                    "previous_workflow": _workflow_to_dict(previous),
                    "promoted_workflow": _workflow_to_dict(candidate),
                    "rationale": rationale,
                },
                prev_hash="",
                entry_hash="",
            )
        )
        audit.close()
        session.update_step(5, "success")
        session.run_step(6, lambda: None)
        return {
            "workflow_id": workflow_id,
            "from_version": current.version,
            "to_version": candidate.version,
        }


def build_group(bindings):
    @click.group(
        name=DRAWER_ID,
        invoke_without_command=True,
        help=str(DRAWER_META["tagline"]),
    )
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("plan", help=str(COMMAND_HELP[COMMAND_IDS[0]]))
    @click.argument("workflow_id")
    @click.option("--tenant", "tenant_id", default="default")
    @click.option("--live-providers", is_flag=True, default=False)
    @click.option("--config", "config_path", default="config.archon.yaml")
    def plan_command(
        workflow_id: str,
        tenant_id: str,
        live_providers: bool,
        config_path: str,
    ) -> None:
        _Plan(bindings).invoke(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            live_providers=live_providers,
            config_path=config_path,
        )

    @group.command("apply", help=str(COMMAND_HELP[COMMAND_IDS[1]]))
    @click.argument("workflow_id")
    @click.option("--tenant", "tenant_id", default="default")
    @click.option("--config", "config_path", default="config.archon.yaml")
    def apply_command(workflow_id: str, tenant_id: str, config_path: str) -> None:
        _Apply(bindings).invoke(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            config_path=config_path,
        )

    return group
