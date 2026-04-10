from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import click

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand, approval_prompt
from archon.cli.copy import DRAWER_COPY, FLOW_COPY
from archon.core.approval_gate import ApprovalDeniedError, ApprovalGate, ApprovalTimeoutError
from archon.interfaces.cli.tui import run_agentic_tui

DRAWER_ID = "core"
COMMAND_IDS = (
    "core.init",
    "core.validate",
    "core.status",
    "core.chat",
    "core.studio",
)
DRAWER_META = DRAWER_COPY[DRAWER_ID]
COMMAND_HELP = DRAWER_META["commands"]
_PROVIDERS = ("anthropic", "openai", "openrouter", "ollama")
_ENV_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}
_PROVIDER_KEY_URLS = {
    "anthropic": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
    "openrouter": "https://openrouter.ai/keys",
}
_VALIDATORS = {
    "anthropic": "_validate_anthropic_key",
    "openai": "_validate_openai_key",
    "openrouter": "_validate_openrouter_key",
}
_STUDIO_HOST = "127.0.0.1"
_STUDIO_PORT = 5173


def _approval_event_sink(gate: ApprovalGate):  # type: ignore[no-untyped-def]
    async def sink(event):
        if str(event.get("type", "")).strip().lower() == "approval_required":
            approval_prompt(gate=gate, event=event)

    return sink


def _counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT status, COUNT(*) FROM worker_tasks GROUP BY status").fetchall()
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


def _key_portal(provider: str) -> str:
    return _PROVIDER_KEY_URLS.get(provider, "")


def _mask_key(value: str) -> str:
    cleaned = str(value or "").strip()
    if len(cleaned) <= 6:
        return "*" * len(cleaned)
    return f"{cleaned[:2]}...{cleaned[-4:]}"


def _await_login(bindings, provider: str) -> None:  # type: ignore[no-untyped-def]
    url = _key_portal(provider)
    if not url:
        return
    env_name = _ENV_KEYS.get(provider, "")
    existing = ""
    if env_name:
        existing = str(os.getenv(env_name) or bindings._read_env_value(env_name) or "").strip()
    click.echo(f"Key portal: {url}")
    if existing:
        return


def _run_with_spinner(label: str, func):  # type: ignore[no-untyped-def]
    frames = "|/-\\"
    done = False
    result = False

    def _worker() -> None:
        nonlocal result, done
        result = bool(func())
        done = True

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    index = 0
    while not done:
        click.echo(f"\r{label} {frames[index % len(frames)]}", nl=False)
        time.sleep(0.12)
        index += 1
    thread.join()
    status = "ok" if result else "failed"
    click.echo(f"\r{label} {status}".ljust(48))
    return result


def _check_key(bindings, provider: str, key: str) -> bool:  # type: ignore[no-untyped-def]
    if provider == "ollama":
        return True
    validator = getattr(bindings, _VALIDATORS[provider])
    return _run_with_spinner(
        f"Authenticating {provider} key",
        lambda: validator(key, timeout_s=5.0),
    )


def validate_config(config_path: str, timeout_seconds: float, *, provider: str | None = None):
    from archon.validate_config import validate_config as _validate_config

    return _validate_config(config_path, provider=provider, timeout_seconds=timeout_seconds)


def _safe_validate_config(config_path: str, timeout_seconds: float):
    try:
        return validate_config(config_path, timeout_seconds)
    except Exception as exc:  # pragma: no cover - defensive guard
        from archon.validate_config import ValidationReport

        return ValidationReport(
            config_path=str(config_path),
            schema_valid=False,
            errors=[str(exc) or repr(exc)],
        )


def _worker_paths():
    from archon.deploy.worker import _runtime_dir, _worker_db_path

    return _runtime_dir, _worker_db_path


def _studio_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "archon" / "studio"


def _build_onboarding_callbacks(bindings):
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


class _Init(ArchonCommand):
    command_id = COMMAND_IDS[0]
    allow_live = False

    def run(self, session, *, config_path: str):  # type: ignore[no-untyped-def,override]
        byok = session.run_step(0, self.bindings._default_byok_config)
        primary = _choice("primary_provider")
        key = ""
        if primary != "ollama":
            _await_login(self.bindings, primary)
            key = click.prompt(
                _key_prompt("primary_key"), hide_input=True, default="", show_default=False
            )
            if key:
                click.echo(f"{primary} key captured: {_mask_key(key)}")
                if not _check_key(self.bindings, primary, key):
                    raise click.ClickException(primary)
                click.echo(f"{primary} key authenticated.")
                self.bindings.write_env(_ENV_KEYS[primary], key)
        fast = session.run_step(1, _choice, "fast_provider")
        if fast not in {"ollama", primary}:
            _await_login(self.bindings, fast)
            fast_key = click.prompt(
                _key_prompt("primary_key"), hide_input=True, default="", show_default=False
            )
            if fast_key:
                click.echo(f"{fast} key captured: {_mask_key(fast_key)}")
                if not _check_key(self.bindings, fast, fast_key):
                    raise click.ClickException(fast)
                click.echo(f"{fast} key authenticated.")
                self.bindings.write_env(_ENV_KEYS[fast], fast_key)
        ollama = session.run_step(2, self.bindings._probe_ollama, 2.0)
        models = [str(name).strip() for name in ollama.get("models", []) if str(name).strip()]
        # Only prompt to pull if Ollama is reachable but has no models available.
        if ollama.get("reachable") and not models:
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
        report = session.run_step(4, _safe_validate_config, config_path, 6.0)
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

    def run(self, session, *, config_path: str, timeout_s: float):  # type: ignore[no-untyped-def,override]
        session.run_step(0, lambda: Path(config_path))
        report = session.run_step(1, validate_config, config_path, timeout_s)
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

    def run(self, session, *, config_path: str):  # type: ignore[no-untyped-def,override]
        runtime_dir, worker_db_path = _worker_paths()
        config = session.run_step(0, self.bindings._load_config, config_path)
        runtime = session.run_step(1, runtime_dir)
        counts = session.run_step(2, _counts, worker_db_path())
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

    async def run(self, session, *, mode: str, config_path: str, yes: bool = False):  # type: ignore[no-untyped-def,override]
        config = (
            session.run_step(0, self.bindings._load_config, config_path)
            if Path(config_path).exists()
            else self.bindings.load_archon_config("__wizard_defaults__.yaml")
        )
        _onboarding = _build_onboarding_callbacks(self.bindings)
        if not yes:
            session.run_step(1, lambda: None)
        session.update_step(2 if yes else 1, "running")
        await run_agentic_tui(
            config=config,
            initial_mode=mode,
            initial_context={},
            config_path=config_path,
        )
        session.update_step(2 if yes else 1, "success")
        return {"mode": mode}


class _Studio(ArchonCommand):
    command_id = COMMAND_IDS[4]
    allow_live = False

    def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        api_base: str,
        host: str,
        port: int,
        dev: bool,
    ):
        studio_dir = session.run_step(0, _studio_dir)
        if not studio_dir.exists():
            raise click.ClickException("Studio path missing.")
        url = f"http://{host}:{port}"
        session.run_step(1, lambda: None)
        if not dev:
            session.run_step(2, lambda: None)
            session.print(
                renderer.detail_panel(
                    self.command_id,
                    [
                        f"path {studio_dir}",
                        f"api {api_base}",
                        f"dev {url}",
                        "run: cd archon/studio",
                        "run: npm install",
                        "run: npm run dev",
                    ],
                )
            )
            return {"path": str(studio_dir), "dev_url": url, "status": "ready"}

        gate = ApprovalGate(supervised_mode=True)
        session.update_step(2, "running")
        try:
            asyncio.run(
                gate.guard(
                    action_type="shell_exec",
                    payload={
                        "agent": "archon-cli",
                        "target": str(studio_dir),
                        "preview": f"npm run dev -- --host {host} --port {port}",
                    },
                    event_sink=_approval_event_sink(gate),
                    timeout_seconds=30.0,
                )
            )
        except (ApprovalDeniedError, ApprovalTimeoutError):
            session.update_step(2, "success")
            return {"result_key": "denied", "status": "denied"}
        env = dict(os.environ)
        env["VITE_ARCHON_API_BASE"] = api_base
        subprocess.run(
            ["npm", "run", "dev", "--", "--host", host, "--port", str(port)],
            check=False,
            cwd=studio_dir,
            env=env,
        )
        session.update_step(2, "success")
        return {"path": str(studio_dir), "dev_url": url, "status": "running"}


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

    @group.command("init", help=str(COMMAND_HELP[COMMAND_IDS[0]]))
    @click.option("--config", "config_path", default="config.archon.yaml")
    def init_command(config_path: str) -> None:
        _Init(bindings).invoke(config_path=config_path)

    @group.command("validate", help=str(COMMAND_HELP[COMMAND_IDS[1]]))
    @click.option("--config", "config_path", default="config.archon.yaml")
    @click.option("--timeout", "timeout_s", default=6.0, type=float)
    def validate_command(config_path: str, timeout_s: float) -> None:
        _Validate(bindings).invoke(config_path=config_path, timeout_s=timeout_s)

    @group.command("status", help=str(COMMAND_HELP[COMMAND_IDS[2]]))
    @click.option("--config", "config_path", default="config.archon.yaml")
    def status_command(config_path: str) -> None:
        _Status(bindings).invoke(config_path=config_path)

    @group.command("chat", help=str(COMMAND_HELP[COMMAND_IDS[3]]))
    @click.option(
        "--mode",
        type=click.Choice(["chat", "debate", "single", "pipeline"]),
        default="chat",
    )
    @click.option("--config", "config_path", default="config.archon.yaml")
    @click.option(
        "-y", "--yes", is_flag=True, default=False, help="Skip prompts, go directly to chat"
    )
    def chat_command(mode: str, config_path: str, yes: bool) -> None:
        _Chat(bindings).invoke(mode=mode, config_path=config_path, yes=yes)

    @group.command("studio", help=str(COMMAND_HELP[COMMAND_IDS[4]]))
    @click.option("--api-base", default="http://localhost:8000")
    @click.option("--host", default=_STUDIO_HOST)
    @click.option("--port", default=_STUDIO_PORT, type=int)
    @click.option("--dev", is_flag=True, default=False)
    def studio_command(api_base: str, host: str, port: int, dev: bool) -> None:
        _Studio(bindings).invoke(api_base=api_base, host=host, port=port, dev=dev)

    return group
