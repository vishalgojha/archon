from __future__ import annotations

import click

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand, TaskLiveDisplay, approval_prompt

DRAWER_ID = "growth"
COMMAND_IDS = ("growth.run",)


def _event_sink(live, gate):  # type: ignore[no-untyped-def]
    async def sink(event):
        live.update(event)
        if str(event.get("type", "")).strip().lower() == "approval_required":
            approval_prompt(gate=gate, event=event)

    return sink


class _Run(ArchonCommand):
    command_id = COMMAND_IDS[0]

    async def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        goal: str,
        live_providers: bool,
        config_path: str,
    ):
        config = session.run_step(0, self.bindings._load_config, config_path)
        orchestrator = session.run_step(
            1,
            self.bindings.Orchestrator,
            config=config,
            live_provider_calls=live_providers,
        )
        live = TaskLiveDisplay()
        live.start()
        session.update_step(2, "running")
        try:
            result = await orchestrator.execute(
                goal=goal,
                mode="growth",
                event_sink=_event_sink(live, orchestrator.approval_gate),
            )
        finally:
            live.stop()
            await orchestrator.aclose()
        session.update_step(2, "success")
        session.run_step(3, lambda: None)
        session.print(renderer.detail_panel(self.command_id, [result.final_answer]))
        actions = list((result.growth or {}).get("recommended_actions", []))
        return {"confidence": result.confidence, "action_count": len(actions)}


def build_group(bindings):
    @click.group(name=DRAWER_ID, invoke_without_command=True)
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("run")
    @click.argument("goal")
    @click.option("--live-providers", is_flag=True, default=False)
    @click.option("--config", "config_path", default="config.archon.yaml")
    def run_command(goal: str, live_providers: bool, config_path: str) -> None:
        _Run(bindings).invoke(
            goal=goal,
            live_providers=live_providers,
            config_path=config_path,
        )

    return group
