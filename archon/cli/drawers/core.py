from __future__ import annotations

import os
import sqlite3
import subprocess
import time
from pathlib import Path

import click

from archon.cli.base_command import ArchonCommand
from archon.cli import renderer
from archon.cli.copy import FLOW_COPY
from archon.deploy.worker import _runtime_dir, _worker_db_path
from archon.interfaces.cli.tui_onboarding import OnboardingCallbacks
from archon.validate_config import validate_config

DRAWER_ID = "core"
COMMAND_IDS = ("core.init", "core.validate", "core.status", "core.chat")
_PROVIDERS = ("anthropic", "openai", "openrouter", "ollama")
_ENV_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}
_VALIDATORS = {
    "anthropic": "_validate_anthropic_key",
    "openai": "_validate_openai_key",
    "openrouter": "_validate_openrouter_key",
}


def _counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) "
            "FROM worker_tasks "
            "GROUP BY status"
        ).fetchall()
    counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    for status, value in rows:
        counts[str(status)] = int(value)
    return counts


def _key_prompt(name: str) -> str:
    return f"{FLOW_COPY['init']['prompts'][name]}:"


def _choice(prompt_key: str) -> str:
    renderer.emit(renderer.detail_panel(prompt_key, list(_PROVIDERS)))
    return click.prompt(
        _key_prompt(prompt_key),
        type=click.Choice(_PROVIDERS, case_sensitive=False),
        show_choices=False,
    )


def _check_key(bindings, provider: str, key: str) -> bool:  # type: ignore[no-untyped-def]
    if provider == "ollama":
        return True
    validator = getattr(bindings, _VALIDATORS[provider])
    return bool(validator(key, timeout_s=5.0))


class _Init(ArchonCommand):
    command_id = COMMAND_IDS[0]

    def run(self, session, *, config_path: str):  # type: ignore[no-untyped-def]
        byok = session.run_step(0, self.bindings._default_byok_config)
        primary = _choice("primary_provider")
        key = ""
        if primary != "ollama":
            key = click.prompt(_key_prompt("primary_key"), hide_input=True, default="", show_default=False)
            if key and not _check_key(self.bindings, primary, key):
                raise click.ClickException(primary)
            if key:
                self.bindings.write_env(_ENV_KEYS[primary], key)
        fast = session.run_step(1, _choice, "fast_provider")
        if fast not in {"ollama", primary}:
            fast_key = click.prompt(_key_prompt("primary_key"), hide_input=True, default="", show_default=False)
            if fast_key and not _check_key(self.bindings, fast, fast_key):
                raise click.ClickException(fast)
            if fast_key:
                self.bindings.write_env(_ENV_KEYS[fast], fast_key)
        ollama = session.run_step(2, self.bindings._probe_ollama, 2.0)
        models = list(ollama.get("models", []))
        if "llama3.2" not in models:
            click.confirm(_key_prompt("ollama_pull"), default=True, abort=False)
            try:
                subprocess.run(["ollama", "pull", "llama3.2"], check=False)
            except OSError:
                pass
        budget_text = click.prompt(_key_prompt("budget_limit"), default="5.00", show_default=False)
        budget_limit = round(float(budget_text), 2)
        byok["primary"] = primary
        byok["coding"] = primary
        byok["vision"] = primary
        byok["fast"] = fast
        byok["embedding"] = "ollama"
        byok["fallback"] = primary if primary != "ollama" else "openrouter"
        byok["budget_per_task_usd"] = min(float(byok.get("budget_per_task_usd", 0.5)), budget_limit)
        byok["budget_per_month_usd"] = round(budget_limit * 30.0, 2)
        config_data = {
            "byok": byok,
            "budget": {"daily_limit_usd": budget_limit, "alert_threshold_pct": 80},
            "supervised_mode": True,
            "deployment_mode": "team_tool",
            "default_tier": "pro",
        }
        session.run_step(3, self.bindings._save_onboarding_config, config_data, config_path)
        report = session.run_step(4, validate_config, config_path, timeout_seconds=6.0)
        renderer.emit(
            renderer.detail_panel(
                self.command_id,
                [
                    renderer.flow_message(
                        "init",
                        "complete",
                        {
                            "config_path": config_path,
                            "validation_status": "PASS" if report.ok else "FAIL",
                        },
                    )
                ],
            )
        )
        return {
            "primary_provider": primary,
            "fast_provider": fast,
            "budget_limit": f"${budget_limit:.2f}",
            "validation_status": "PASS" if report.ok else "FAIL",
        }


class _Validate(ArchonCommand):
    command_id = COMMAND_IDS[1]

    def run(self, session, *, config_path: str, timeout_s: float):  # type: ignore[no-untyped-def]
        session.run_step(0, lambda: Path(config_path))
        report = session.run_step(1, validate_config, config_path, timeout_seconds=timeout_s)
        lines = [f"schema {'PASS' if report.schema_valid else 'FAIL'}"]
        for row in report.provider_health:
            lines.append(f"{row.provider} {row.status} {row.detail}".strip())
        session.run_step(2, lambda: None)
        session.run_step(3, lambda: None)
        session.print(renderer.detail_panel(self.command_id, lines))
        return {
            "status": "PASS" if report.ok else "FAIL",
            "provider_count": len(report.provider_health),
            "failure_count": len(report.failed_provider_checks),
            "result_key": "success" if report.ok else "failure",
        }


class _Status(ArchonCommand):
    command_id = COMMAND_IDS[2]

    def run(self, session, *, config_path: str):  # type: ignore[no-untyped-def]
        config = session.run_step(0, self.bindings._load_config, config_path)
        runtime = session.run_step(1, _runtime_dir)
        counts = session.run_step(2, _counts, _worker_db_path())
        version = self.bindings._resolve_version()
        roles = []
        for role in ("primary", "coding", "vision", "fast", "embedding", "fallback"):
            roles.append(f"{role} {getattr(config.byok, role, '-')}")
        roles.append(f"runtime {runtime}")
        roles.append(f"pending {counts['pending']}")
        roles.append(f"running {counts['running']}")
        roles.append(f"completed {counts['completed']}")
        roles.append(f"failed {counts['failed']}")
        session.run_step(3, lambda: None)
        session.print(renderer.detail_panel(self.command_id, roles))
        return {
            "version": version,
            "runtime_dir": str(runtime),
            "queue_depth": counts["pending"] + counts["running"],
            "worker_count": counts["running"],
        }


class _Chat(ArchonCommand):
    command_id = COMMAND_IDS[3]

    async def run(self, session, *, mode: str, config_path: str):  # type: ignore[no-untyped-def]
        config = (
            session.run_step(0, self.bindings._load_config, config_path)
            if Path(config_path).exists()
            else self.bindings.load_archon_config("__wizard_defaults__.yaml")
        )
        onboarding = OnboardingCallbacks(
            default_byok_config=self.bindings._default_byok_config,
            probe_ollama=self.bindings._probe_ollama,
            validate_openrouter_key=self.bindings._validate_openrouter_key,
            validate_openai_key=self.bindings._validate_openai_key,
            validate_anthropic_key=self.bindings._validate_anthropic_key,
            save_config=self.bindings._save_onboarding_config,
            run_validation=self.bindings._run_validation_dry_run,
            read_env_value=self.bindings._read_env_value,
            write_env=self.bindings.write_env,
            load_config=self.bindings._load_config,
        )
        session.run_step(1, lambda: None)
        session.update_step(2, "running")
        await self.bindings.run_agentic_tui(
            config=config,
            initial_mode=mode,
            live_provider_calls=self.bindings._should_default_tui_to_live(config),
            initial_context={},
            config_path=config_path,
            onboarding=onboarding,
            show_launcher=True,
        )
        session.update_step(2, "success")
        return {"mode": mode}


def build_group(bindings):
    @click.group(name=DRAWER_ID, invoke_without_command=True)
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("init")
    @click.option("--config", "config_path", default="config.archon.yaml")
    def init_command(config_path: str) -> None:
        _Init(bindings).invoke(config_path=config_path)

    @group.command("validate")
    @click.option("--config", "config_path", default="config.archon.yaml")
    @click.option("--timeout", "timeout_s", default=6.0, type=float)
    def validate_command(config_path: str, timeout_s: float) -> None:
        _Validate(bindings).invoke(config_path=config_path, timeout_s=timeout_s)

    @group.command("status")
    @click.option("--config", "config_path", default="config.archon.yaml")
    def status_command(config_path: str) -> None:
        _Status(bindings).invoke(config_path=config_path)

    @group.command("chat")
    @click.option("--mode", type=click.Choice(["debate", "growth", "auto"]), default="auto")
    @click.option("--config", "config_path", default="config.archon.yaml")
    def chat_command(mode: str, config_path: str) -> None:
        _Chat(bindings).invoke(mode=mode, config_path=config_path)

    return group
