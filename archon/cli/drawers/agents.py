from __future__ import annotations

from pathlib import Path

import click

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand, TaskLiveDisplay, approval_prompt
from archon.cli.copy import DRAWER_COPY
from archon.core.orchestrator import Orchestrator
from archon.interfaces.cli.tui import run_agentic_tui

DRAWER_ID = "agents"
COMMAND_IDS = ("agents.task", "agents.debate", "agents.tui")
DRAWER_META = DRAWER_COPY[DRAWER_ID]
COMMAND_HELP = DRAWER_META["commands"]


def _event_sink(live, gate):  # type: ignore[no-untyped-def]
    async def sink(event):
        live.update(event)
        if str(event.get("type", "")).strip().lower() == "approval_required":
            approval_prompt(gate=gate, event=event)

    return sink


def _build_onboarding(bindings):  # type: ignore[no-untyped-def]
    from archon.interfaces.cli.tui_onboarding import OnboardingCallbacks

    return OnboardingCallbacks(
        default_byok_config=bindings._default_byok_config,
        probe_ollama=bindings._probe_ollama,
        validate_openrouter_key=bindings._validate_openrouter_key,
        validate_openai_key=bindings._validate_openai_key,
        validate_anthropic_key=bindings._validate_anthropic_key,
        save_config=bindings._save_onboarding_config,
        run_validation=bindings._run_validation,
        read_env_value=bindings._read_env_value,
        write_env=bindings.write_env,
        load_config=bindings._load_config,
    )


class _Task(ArchonCommand):
    command_id = COMMAND_IDS[0]

    def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        goal: str,
        mode: str,
        base_url: str,
        tenant_id: str,
        tier: str,
        token: str,
        context_text: str,
        context_file: Path | None,
        timeout_s: float,
    ):
        effective_mode = "debate"
        context = session.run_step(
            1, self.bindings._parse_context, context_text or None, context_file
        )
        headers = self.bindings._create_api_headers(
            token=token or None,
            tenant_id=tenant_id,
            tier=tier,
        )
        payload = session.run_step(
            2,
            self.bindings._request_json,
            "POST",
            f"{self.bindings._normalize_base_url(base_url)}/v1/tasks",
            headers=headers,
            json_body={"goal": goal, "mode": effective_mode, "context": context},
            timeout_s=timeout_s,
        )
        session.run_step(3, lambda: None)
        session.print(
            renderer.detail_panel(
                self.command_id,
                [
                    str(payload.get("final_answer", "")),
                    f"confidence {int(payload.get('confidence', 0) or 0)}%",
                ],
            )
        )
        spent = float((payload.get("budget") or {}).get("spent_usd", 0.0) or 0.0)
        return {
            "mode": str(payload.get("mode", effective_mode)),
            "confidence": int(payload.get("confidence", 0) or 0),
            "spent_usd": f"${spent:.4f}",
        }


class _Debate(ArchonCommand):
    command_id = COMMAND_IDS[1]

    async def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        question: str,
        mode: str,
        budget: float | None,
        config_path: str,
    ):
        config = session.run_step(0, self.bindings._load_config, config_path)
        if budget is not None:
            config.byok.budget_per_task_usd = float(budget)
        effective_mode = "debate"
        orchestrator = session.run_step(
            1,
            Orchestrator,
            config=config,
        )
        live = TaskLiveDisplay()
        live.start()
        session.update_step(2, "running")
        try:
            result = await orchestrator.execute(
                goal=question,
                mode=effective_mode,
                event_sink=_event_sink(live, orchestrator.approval_gate),
            )
        finally:
            live.stop()
            await orchestrator.aclose()
        session.update_step(2, "success")
        session.run_step(3, lambda: None)
        session.print(renderer.detail_panel(self.command_id, [result.final_answer]))
        spent = float(result.budget.get("spent_usd", 0.0) or 0.0)
        return {
            "mode": result.mode,
            "confidence": result.confidence,
            "spent_usd": f"${spent:.4f}",
        }


class _Tui(ArchonCommand):
    command_id = COMMAND_IDS[2]

    async def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        mode: str,
        budget: float | None,
        context_text: str,
        context_file: Path | None,
        config_path: str,
    ):
        config = (
            session.run_step(0, self.bindings._load_config, config_path)
            if Path(config_path).exists()
            else self.bindings.load_archon_config("__wizard_defaults__.yaml")
        )
        if budget is not None:
            config.byok.budget_per_task_usd = float(budget)
        context = session.run_step(
            1, self.bindings._parse_context, context_text or None, context_file
        )
        onboarding = _build_onboarding(self.bindings)
        session.update_step(2, "running")
        await run_agentic_tui(
            config=config,
            initial_mode=mode,
            initial_context=context,
            config_path=config_path,
            onboarding=onboarding,
            show_launcher=True,
        )
        session.update_step(2, "success")
        session.run_step(3, lambda: None)
        return {"mode": mode}


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

    @group.command("task", help=str(COMMAND_HELP[COMMAND_IDS[0]]))
    @click.argument("goal")
    @click.option("--mode", type=click.Choice(["debate"]), default="debate")
    @click.option("--base-url", default="http://127.0.0.1:8000")
    @click.option("--tenant-id", default="default")
    @click.option("--tier", type=click.Choice(["free", "pro", "enterprise"]), default="pro")
    @click.option("--token", default="")
    @click.option("--context", "context_text", default="")
    @click.option(
        "--context-file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        default=None,
    )
    @click.option("--timeout", "timeout_s", default=60.0, type=float)
    def task_command(
        goal: str,
        mode: str,
        base_url: str,
        tenant_id: str,
        tier: str,
        token: str,
        context_text: str,
        context_file: Path | None,
        timeout_s: float,
    ) -> None:
        _Task(bindings).invoke(
            goal=goal,
            mode=mode,
            base_url=base_url,
            tenant_id=tenant_id,
            tier=tier,
            token=token,
            context_text=context_text,
            context_file=context_file,
            timeout_s=timeout_s,
        )

    @group.command("debate", help=str(COMMAND_HELP[COMMAND_IDS[1]]))
    @click.argument("question")
    @click.option("--mode", type=click.Choice(["debate"]), default="debate")
    @click.option("--budget", type=float, default=None)
    @click.option("--config", "config_path", default="config.archon.yaml")
    def debate_command(
        question: str,
        mode: str,
        budget: float | None,
        config_path: str,
    ) -> None:
        _Debate(bindings).invoke(
            question=question,
            mode=mode,
            budget=budget,
            config_path=config_path,
        )

    @group.command("tui", help=str(COMMAND_HELP[COMMAND_IDS[2]]))
    @click.option("--mode", type=click.Choice(["debate"]), default="debate")
    @click.option("--budget", type=float, default=None)
    @click.option("--context", "context_text", default="")
    @click.option(
        "--context-file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        default=None,
    )
    @click.option("--config", "config_path", default="config.archon.yaml")
    def tui_command(
        mode: str,
        budget: float | None,
        context_text: str,
        context_file: Path | None,
        config_path: str,
    ) -> None:
        _Tui(bindings).invoke(
            mode=mode,
            budget=budget,
            context_text=context_text,
            context_file=context_file,
            config_path=config_path,
        )

    return group
