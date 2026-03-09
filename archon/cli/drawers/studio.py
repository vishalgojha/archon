from __future__ import annotations

from pathlib import Path

import click

from archon.cli.base_command import ArchonCommand
from archon.cli import renderer

DRAWER_ID = "studio"
COMMAND_IDS = ("studio.open", "studio.run")


class _Open(ArchonCommand):
    command_id = COMMAND_IDS[0]

    def run(self, session, *, base_url: str):  # type: ignore[no-untyped-def]
        session.run_step(
            0,
            self.bindings._open_web_shell,
            base_url,
            route="studio",
            command_name="studio",
        )
        session.run_step(1, lambda: None)
        return {"url": f"{base_url.rstrip('/')}/studio"}


class _Run(ArchonCommand):
    command_id = COMMAND_IDS[1]

    async def run(  # type: ignore[no-untyped-def]
        self,
        session,
        *,
        workflow_file: Path,
        dry_run: bool,
        live_providers: bool,
        config_path: str,
    ):
        config = session.run_step(0, self.bindings._load_config, config_path)
        with workflow_file.open("r", encoding="utf-8") as handle:
            payload = self.bindings.yaml.safe_load(handle) or {}
        if not isinstance(payload, dict):
            raise click.ClickException("workflow file")
        if dry_run:
            step_count = len(payload.get("steps", [])) if isinstance(payload.get("steps"), list) else 0
            session.run_step(1, lambda: None)
            return {
                "result_key": "dry_run",
                "workflow_name": str(payload.get("name", workflow_file.name)),
                "step_count": step_count,
            }
        goal = str(payload.get("goal", f"Run workflow from {workflow_file.name}"))
        mode = str(payload.get("mode", "debate")).lower()
        if mode not in {"debate", "growth"}:
            mode = "debate"
        session.update_step(1, "running")
        orchestrator = self.bindings.Orchestrator(
            config=config,
            live_provider_calls=live_providers,
        )
        try:
            result = await orchestrator.execute(goal=goal, mode=mode)
        finally:
            await orchestrator.aclose()
        session.update_step(1, "success")
        session.run_step(2, lambda: None)
        session.run_step(3, lambda: None)
        session.print(renderer.detail_panel(self.command_id, [result.final_answer]))
        return {
            "workflow_name": str(payload.get("name", workflow_file.name)),
            "mode": mode,
        }


def build_group(bindings):
    @click.group(name=DRAWER_ID, invoke_without_command=True)
    @click.option("--base-url", default="")
    @click.pass_context
    def group(ctx: click.Context, base_url: str) -> None:
        if ctx.invoked_subcommand is None:
            if base_url:
                _Open(bindings).invoke(base_url=base_url)
                return
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("open")
    @click.option("--base-url", default="http://127.0.0.1:8000")
    def open_command(base_url: str) -> None:
        _Open(bindings).invoke(base_url=base_url)

    @group.command("run")
    @click.argument(
        "workflow_file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @click.option("--dry-run", is_flag=True, default=False)
    @click.option("--live-providers", is_flag=True, default=False)
    @click.option("--config", "config_path", default="config.archon.yaml")
    def run_command(
        workflow_file: Path,
        dry_run: bool,
        live_providers: bool,
        config_path: str,
    ) -> None:
        _Run(bindings).invoke(
            workflow_file=workflow_file,
            dry_run=dry_run,
            live_providers=live_providers,
            config_path=config_path,
        )

    return group
