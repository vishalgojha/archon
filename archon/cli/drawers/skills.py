from __future__ import annotations

import json
from typing import Any

import click

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand, CommandSession, approval_prompt
from archon.cli.copy import DRAWER_COPY
from archon.core.approval_gate import ApprovalDeniedError, ApprovalGate, ApprovalTimeoutError
from archon.skills.skill_creator import SkillCreator
from archon.skills.skill_registry import SkillRegistry

DRAWER_ID = "skills"
COMMAND_IDS = ("skills.list", "skills.propose", "skills.apply")
DRAWER_META = DRAWER_COPY[DRAWER_ID]
COMMAND_HELP = DRAWER_META["commands"]


def _approval_event_sink(gate: ApprovalGate):  # type: ignore[no-untyped-def]
    async def sink(event):
        if str(event.get("type", "")).strip().lower() == "approval_required":
            approval_prompt(gate=gate, event=event)

    return sink


class _List(ArchonCommand):
    command_id = COMMAND_IDS[0]

    def run(self, session, *, config_path: str):  # type: ignore[no-untyped-def,override]
        session.run_step(0, lambda: config_path)
        registry = session.run_step(1, SkillRegistry)
        skills = registry.list_skills()
        lines = [
            f"{skill.name} [{skill.state}] provider={skill.provider_preference or '-'} "
            f"tier={skill.cost_tier}"
            for skill in skills
        ]
        session.run_step(2, lambda: None)
        session.print(renderer.detail_panel(self.command_id, lines or ["No skills registered."]))
        return {"count": len(skills)}


class _Propose(ArchonCommand):
    command_id = COMMAND_IDS[1]
    allow_live = False

    async def run(  # type: ignore[override]
        self, session: CommandSession, *, config_path: str, limit: int, confidence: int
    ) -> dict[str, Any]:
        cfg = session.run_step(0, self.bindings._load_config, config_path)
        gate = ApprovalGate(supervised_mode=True)
        creator = SkillCreator(config=cfg, approval_gate=gate)
        gap_tasks = session.run_step(
            1, creator.find_gap_tasks, limit=limit, confidence_threshold=confidence
        )
        session.update_step(2, "running")
        try:
            proposal = await creator.propose_skill(
                gap_tasks=gap_tasks, event_sink=_approval_event_sink(gate)
            )
        except (ApprovalDeniedError, ApprovalTimeoutError):
            session.update_step(2, "success")
            return {"result_key": "denied", "status": "denied"}
        finally:
            creator.close()
        session.update_step(2, "success")
        if proposal is None:
            return {"result_key": "empty", "status": "no_gaps"}
        session.print(
            renderer.detail_panel(
                self.command_id,
                [json.dumps(proposal.skill.to_dict(), indent=2)],
            )
        )
        return {"skill": proposal.skill.name, "status": "staged"}


class _Apply(ArchonCommand):
    command_id = COMMAND_IDS[2]
    allow_live = False

    async def run(  # type: ignore[override]
        self, session: CommandSession, *, name: str, config_path: str
    ) -> dict[str, Any]:
        cfg = session.run_step(0, self.bindings._load_config, config_path)
        gate = ApprovalGate(supervised_mode=True)
        creator = SkillCreator(config=cfg, approval_gate=gate)
        session.update_step(1, "running")
        try:
            result = await creator.apply_skill(name=name, event_sink=_approval_event_sink(gate))
        except (ApprovalDeniedError, ApprovalTimeoutError):
            session.update_step(1, "success")
            return {"result_key": "denied", "status": "denied"}
        finally:
            creator.close()
        session.update_step(1, "success")
        session.print(renderer.detail_panel(self.command_id, [json.dumps(result, indent=2)]))
        if result.get("status") == "rejected":
            result["result_key"] = "rejected"
        return result


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

    @group.command("list", help=str(COMMAND_HELP[COMMAND_IDS[0]]))
    @click.option("--config", "config_path", default="config.archon.yaml")
    def list_command(config_path: str) -> None:
        _List(bindings).invoke(config_path=config_path)

    @group.command("propose", help=str(COMMAND_HELP[COMMAND_IDS[1]]))
    @click.option("--config", "config_path", default="config.archon.yaml")
    @click.option("--limit", default=50, type=int)
    @click.option("--confidence", default=70, type=int)
    def propose_command(config_path: str, limit: int, confidence: int) -> None:
        _Propose(bindings).invoke(config_path=config_path, limit=limit, confidence=confidence)

    @group.command("apply", help=str(COMMAND_HELP[COMMAND_IDS[2]]))
    @click.argument("name")
    @click.option("--config", "config_path", default="config.archon.yaml")
    def apply_command(name: str, config_path: str) -> None:
        _Apply(bindings).invoke(name=name, config_path=config_path)

    return group
