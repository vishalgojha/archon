"""ARCHON command line interface."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import secrets
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import click
import httpx
import yaml

from archon import runtime_installer
from archon.api.auth import create_tenant_token
from archon.config import ArchonConfig, load_archon_config
from archon.core.approval_gate import ApprovalGate
from archon.core.orchestrator import Orchestrator
from archon.deploy.cli import deploy_group
from archon.federation.peer_discovery import Peer, PeerRegistry
from archon.interfaces.cli.tui import run_agentic_tui
from archon.interfaces.cli.tui_onboarding import OnboardingCallbacks
from archon.marketplace.payout_orchestrator import PayoutOrchestrator
from archon.marketplace.revenue_share import PayoutQueue, RevenueShareLedger
from archon.memory.store import MemoryStore
from archon.partners.registry import PartnerRegistry
from archon.redteam import RegressionRunner
from archon.validate_config import main as validate_config_main
from archon.versioning import resolve_git_sha, resolve_version

try:  # pragma: no cover - optional dependency
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except Exception:  # pragma: no cover - optional dependency
    box = None
    Console = None
    Panel = None
    Table = None
    Text = None

DEFAULT_CONFIG_PATH = "config.archon.yaml"
DEFAULT_SERVER_URL = "http://127.0.0.1:8000"
DEFAULT_INSTALL_ROOT = str(runtime_installer.default_install_root())
DEFAULT_INSTALL_REPO_ROOT = str(Path(__file__).resolve().parents[1])
ARCHON_ASCII_ART = (
    "    ___    ____  ________  ______  _   __",
    "   /   |  / __ \\/ ____/ / / / __ \\/ | / /",
    "  / /| | / /_/ / /   / /_/ / / / /  |/ / ",
    " / ___ |/ _, _/ /___/ __  / /_/ / /|  /  ",
    "/_/  |_/_/ |_|\\____/_/ /_/\\____/_/ |_/   ",
)


class _Printer:
    def __init__(self) -> None:
        self._console = Console() if Console is not None else None

    def print(self, message: str) -> None:
        if self._console is not None:
            self._console.print(message)
        else:
            click.echo(message)

    def table(self, columns: list[str], rows: list[list[Any]]) -> None:
        if self._console is not None and Table is not None:
            table = Table(show_header=True, header_style="bold cyan")
            for column in columns:
                table.add_column(column)
            for row in rows:
                table.add_row(*[str(item) for item in row])
            self._console.print(table)
            return

        if not rows:
            self.print(" | ".join(columns))
            return
        widths = [len(column) for column in columns]
        for row in rows:
            for idx, value in enumerate(row):
                widths[idx] = max(widths[idx], len(str(value)))
        header = " | ".join(column.ljust(widths[idx]) for idx, column in enumerate(columns))
        self.print(header)
        self.print("-+-".join("-" * width for width in widths))
        for row in rows:
            self.print(" | ".join(str(value).ljust(widths[idx]) for idx, value in enumerate(row)))


def _load_config(path: str = DEFAULT_CONFIG_PATH):
    return load_archon_config(path)


@contextmanager
def _load_env_file(env_path: str | Path = ".env"):
    path = Path(env_path)
    if not path.exists():
        yield
        return
    loaded_keys: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        normalized_key = key.strip()
        if normalized_key in os.environ:
            continue
        os.environ[normalized_key] = value.strip()
        loaded_keys.append(normalized_key)
    try:
        yield
    finally:
        for key in loaded_keys:
            os.environ.pop(key, None)


def write_env(key: str, value: str, env_path: str | Path = ".env") -> None:
    """Upsert a key=value line in .env file."""

    path = Path(env_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated = False
    output: list[str] = []
    prefix = f"{key}="
    for line in lines:
        if line.startswith(prefix):
            if not updated:
                output.append(f"{key}={value}")
                updated = True
            continue
        output.append(line)
    if not updated:
        output.append(f"{key}={value}")
    path.write_text("\n".join(output).rstrip("\n") + "\n", encoding="utf-8")


def _read_env_value(key: str, env_path: str | Path = ".env") -> str | None:
    path = Path(env_path)
    if not path.exists():
        return None
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _read_line(prompt: str) -> str:
    click.echo(prompt, nl=False)
    return click.get_text_stream("stdin").readline().rstrip("\r\n")


def _prompt_choice(
    prompt: str,
    choices: tuple[str, ...],
    *,
    default: str | None = None,
    yes: bool = False,
) -> str:
    if yes:
        return default if default is not None else choices[0]
    while True:
        value = _read_line(prompt).strip()
        if not value and default is not None:
            return default
        if value in choices:
            return value
        click.echo(f"Enter one of: {'/'.join(choices)}")


def _prompt_yes_no(prompt: str, *, default: bool = False, yes: bool = False) -> bool:
    if yes:
        return default
    while True:
        value = _read_line(prompt).strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        click.echo("Enter y or n.")


def _prompt_budget(default: float = 5.0, *, yes: bool = False) -> float:
    if yes:
        return round(default, 2)
    while True:
        value = _read_line(f"Daily budget in USD [default: {default:.2f}]:").strip()
        if not value:
            return round(default, 2)
        try:
            parsed = round(float(value), 2)
        except ValueError:
            click.echo("Budget must be between 0.10 and 1000.00.")
            continue
        if 0.10 <= parsed <= 1000.00:
            return parsed
        click.echo("Budget must be between 0.10 and 1000.00.")


def _prompt_alert_threshold(default: int = 80, *, yes: bool = False) -> int:
    if yes:
        return default
    while True:
        value = _read_line(f"Alert threshold % [default: {default}]:").strip()
        if not value:
            return default
        try:
            parsed = int(value)
        except ValueError:
            click.echo("Alert threshold must be between 1 and 99.")
            continue
        if 1 <= parsed <= 99:
            return parsed
        click.echo("Alert threshold must be between 1 and 99.")


def _default_byok_config() -> dict[str, Any]:
    return load_archon_config("__wizard_defaults__.yaml").byok.model_dump()


def _should_default_tui_to_live(config: Any) -> bool:
    byok = getattr(config, "byok", None)
    if not isinstance(config, ArchonConfig) or byok is None:
        return False
    return (
        byok.primary == "ollama"
        and byok.coding == "ollama"
        and byok.fast == "ollama"
        and byok.fallback == "ollama"
    )


def _probe_ollama(timeout_s: float = 2.0) -> dict[str, Any]:
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=timeout_s)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return {"reachable": False, "models": [], "detail": "unreachable"}

    models: list[str] = []
    raw_models = payload.get("models", [])
    if isinstance(raw_models, list):
        for item in raw_models:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("model") or "").strip()
            else:
                name = str(item).strip()
            if name:
                models.append(name)
    return {"reachable": True, "models": models, "detail": "reachable"}


def _validate_openrouter_key(api_key: str, timeout_s: float = 5.0) -> bool:
    try:
        response = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
        )
        return response.is_success
    except httpx.HTTPError:
        return False


def _validate_openai_key(api_key: str, timeout_s: float = 5.0) -> bool:
    try:
        response = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
        )
        return response.is_success
    except httpx.HTTPError:
        return False


def _validate_anthropic_key(api_key: str, timeout_s: float = 5.0) -> bool:
    try:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-5-haiku-latest",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=timeout_s,
        )
        return response.is_success
    except httpx.HTTPError:
        return False


def _has_llama3_model(models: list[str]) -> bool:
    return any(str(model).strip().lower().startswith("llama3") for model in models)


def _configure_free_stack(
    byok: dict[str, Any],
    *,
    env_path: str | Path = ".env",
    yes: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    ollama_probe = _probe_ollama(timeout_s=2.0)
    models = list(ollama_probe.get("models", []))
    if ollama_probe.get("reachable"):
        click.echo("✔ Ollama detected")
        click.echo("  Models: " + (", ".join(models) if models else "none detected"))
        if _has_llama3_model(models):
            click.echo("✔ llama3 ready")
        else:
            click.echo("  Run: ollama pull llama3.2")
    else:
        click.echo("⚠ Ollama not found.")
        click.echo("  Download from https://ollama.ai then run:")
        click.echo("    ollama pull llama3.2")
        click.echo("    ollama pull nomic-embed-text")
        if not yes and not _prompt_yes_no("Continue anyway? [y/N]:", default=False):
            return False, "", ollama_probe

    openrouter_key = (
        "" if yes else _read_line("OpenRouter API key (free tier, press Enter to skip):").strip()
    )
    if openrouter_key:
        if _validate_openrouter_key(openrouter_key, timeout_s=5.0):
            click.echo("✔ OpenRouter key valid")
        else:
            click.echo("⚠ Key did not validate — saved anyway")
        write_env("OPENROUTER_API_KEY", openrouter_key, env_path=env_path)

    byok.update(
        {
            "primary": "ollama",
            "coding": "ollama",
            "vision": "ollama",
            "fast": "ollama",
            "embedding": "ollama",
            "fallback": "openrouter" if openrouter_key else "ollama",
            "prefer_cheapest": True,
            "free_tier_first": True,
        }
    )
    provider_summary = "ollama + openrouter fallback" if openrouter_key else "ollama (local models)"
    return True, provider_summary, ollama_probe


def _configure_pro_stack(
    byok: dict[str, Any],
    *,
    env_path: str | Path = ".env",
    yes: bool = False,
) -> tuple[bool, str, dict[str, Any] | None]:
    anthropic_key = (
        "" if yes else _read_line("Anthropic API key (sk-ant-...) or Enter to skip:").strip()
    )
    if anthropic_key:
        if _validate_anthropic_key(anthropic_key, timeout_s=5.0):
            click.echo("✔ Anthropic key valid")
        else:
            click.echo("⚠ Could not validate — saved anyway")
        write_env("ANTHROPIC_API_KEY", anthropic_key, env_path=env_path)

    openai_key = "" if yes else _read_line("OpenAI API key (sk-...) or Enter to skip:").strip()
    if openai_key:
        if _validate_openai_key(openai_key, timeout_s=5.0):
            click.echo("✔ OpenAI key valid")
        else:
            click.echo("⚠ Could not validate — saved anyway")
        write_env("OPENAI_API_KEY", openai_key, env_path=env_path)

    if not anthropic_key and not openai_key:
        click.echo("⚠ No keys provided. Falling back to free stack.")
        return _configure_free_stack(byok, env_path=env_path, yes=yes)

    if anthropic_key and openai_key:
        byok.update(
            {
                "primary": "anthropic",
                "coding": "openai",
                "vision": "openai",
                "fast": "anthropic",
                "embedding": "ollama",
                "fallback": "openai",
                "prefer_cheapest": False,
                "free_tier_first": False,
            }
        )
        return True, "anthropic (claude-sonnet-4-5)", None

    if anthropic_key:
        byok.update(
            {
                "primary": "anthropic",
                "coding": "anthropic",
                "vision": "anthropic",
                "fast": "anthropic",
                "embedding": "ollama",
                "fallback": "anthropic",
                "prefer_cheapest": False,
                "free_tier_first": False,
            }
        )
        return True, "anthropic (claude-sonnet-4-5)", None

    byok.update(
        {
            "primary": "openai",
            "coding": "openai",
            "vision": "openai",
            "fast": "openai",
            "embedding": "ollama",
            "fallback": "openai",
            "prefer_cheapest": False,
            "free_tier_first": False,
        }
    )
    return True, "openai (gpt-4o)", None


def _validation_payload(config_data: dict[str, Any]) -> dict[str, Any]:
    byok = dict(config_data.get("byok") or {})
    budget = dict(config_data.get("budget") or {})
    daily_limit = float(budget.get("daily_limit_usd", 5.0) or 5.0)
    alert_threshold_pct = int(budget.get("alert_threshold_pct", 80) or 80)
    return {
        "providers": {
            "primary": byok.get("primary", "anthropic"),
            "coding": byok.get("coding", "openai"),
            "vision": byok.get("vision", "openai"),
            "fast": byok.get("fast", "groq"),
            "embedding": byok.get("embedding", "ollama"),
            "fallback": byok.get("fallback", "openrouter"),
            "ollama_base_url": byok.get("ollama_base_url", "http://localhost:11434/v1"),
            "openrouter_base_url": byok.get(
                "openrouter_base_url",
                "https://openrouter.ai/api/v1",
            ),
            "custom_endpoints": list(byok.get("custom_endpoints", [])),
        },
        "budget": {
            "per_request_usd": float(byok.get("budget_per_task_usd", 0.50) or 0.50),
            "daily_usd": daily_limit,
            "monthly_usd": float(byok.get("budget_per_month_usd", round(daily_limit * 30.0, 2))),
            "alert_threshold": round(alert_threshold_pct / 100.0, 4),
        },
        "tenants": [],
        "memory": {"backend": "sqlite"},
        "evolution": {"enabled": False, "max_experiments_per_day": 0},
    }


def _run_validation_dry_run(config_data: dict[str, Any], config_path: str) -> int:
    temp_path: Path | None = None
    try:
        config_dir = Path(config_path).resolve().parent
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".yaml",
            delete=False,
            dir=str(config_dir),
        ) as handle:
            yaml.safe_dump(_validation_payload(config_data), handle, sort_keys=False)
            temp_path = Path(handle.name)
        with io.StringIO() as stdout_buffer, io.StringIO() as stderr_buffer:
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                return int(validate_config_main(["--config", str(temp_path), "--dry-run"]))
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _print_validation_statuses(
    config_data: dict[str, Any],
    *,
    ollama_probe: dict[str, Any] | None = None,
    env_path: str | Path = ".env",
) -> None:
    byok = dict(config_data.get("byok") or {})
    ordered_providers: list[str] = []
    for role in ("primary", "coding", "vision", "fast", "embedding", "fallback"):
        provider = str(byok.get(role, "") or "").strip()
        if provider and provider not in ordered_providers:
            ordered_providers.append(provider)

    provider_env_keys = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "groq": "GROQ_API_KEY",
    }
    cached_ollama_probe = ollama_probe

    for provider in ordered_providers:
        status = True
        detail = "manual configuration"
        if provider == "ollama":
            if cached_ollama_probe is None:
                cached_ollama_probe = _probe_ollama(timeout_s=2.0)
            reachable = bool(cached_ollama_probe.get("reachable"))
            status = reachable
            detail = "reachable" if reachable else "not reachable"
        elif provider in provider_env_keys:
            configured = bool(
                str(
                    _read_env_value(provider_env_keys[provider], env_path)
                    or os.getenv(provider_env_keys[provider], "")
                ).strip()
            )
            status = configured
            detail = "key configured" if configured else "no key (skipped)"
        symbol = "✔" if status else "✗"
        click.echo(f"  {symbol} {provider:<10} — {detail}")


def _save_onboarding_config(config_data: dict[str, Any], config_path: str) -> None:
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(config_data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _plain_onboarding_banner() -> str:
    return "\n".join(
        [
            "+" + "-" * 53 + "+",
            "|                                                     |",
            *[f"|  {line.ljust(49)}  |" for line in ARCHON_ASCII_ART],
            "|                                                     |",
            "|  Multi-Agent Orchestration Network                  |",
            "|  This wizard takes ~2 minutes.                      |",
            "|  Re-run anytime: archon onboard                     |",
            "|                                                     |",
            "+" + "-" * 53 + "+",
        ]
    )


def _print_onboarding_banner() -> None:
    if Console is None or Panel is None or Text is None or box is None:
        click.echo(_plain_onboarding_banner())
        return

    banner = Text()
    for line in ARCHON_ASCII_ART:
        banner.append(line, style="bold #38d9b5 on white")
        banner.append("\n")
    banner.append("\n")
    banner.append("Multi-Agent Orchestration Network\n", style="bold #28424d on white")
    banner.append("This wizard takes ~2 minutes.\n", style="#5a6b75 on white")
    banner.append("Re-run anytime: ", style="#5a6b75 on white")
    banner.append("archon onboard", style="bold #38d9b5 on white")

    Console().print(
        Panel.fit(
            banner,
            border_style="bold #8de8d4",
            box=box.ROUNDED,
            padding=(1, 2),
            style="on white",
        )
    )


def _run_onboarding_wizard(
    config_path: str = DEFAULT_CONFIG_PATH,
    *,
    yes: bool = False,
) -> bool:
    env_path = Path(".env")
    _print_onboarding_banner()
    if not yes:
        _read_line("Press Enter to continue...")

    click.echo("")
    click.echo("How do you want to run ARCHON?")
    click.echo("")
    click.echo("[1] Free  — Ollama (local) + OpenRouter free tier")
    click.echo("            No API keys needed. Runs on your machine.")
    click.echo("")
    click.echo("[2] Pro   — Anthropic / OpenAI")
    click.echo("            Best quality. Requires API keys.")
    click.echo("")
    click.echo("[3] Custom — I'll configure providers manually.")
    click.echo("")
    stack_choice = _prompt_choice(
        "Enter choice [1/2/3]:",
        ("1", "2", "3"),
        default="1",
        yes=yes,
    )

    click.echo("")
    byok = _default_byok_config()
    provider_summary = "custom (edit config)"
    ollama_probe: dict[str, Any] | None = None
    if stack_choice == "1":
        configured, provider_summary, ollama_probe = _configure_free_stack(
            byok,
            env_path=env_path,
            yes=yes,
        )
        if not configured:
            return False
    elif stack_choice == "2":
        configured, provider_summary, ollama_probe = _configure_pro_stack(
            byok,
            env_path=env_path,
            yes=yes,
        )
        if not configured:
            return False
    else:
        click.echo("Edit config.archon.yaml directly after setup.")
        click.echo("Documentation: https://github.com/your-repo/archon")
        click.echo("Skipping provider configuration.")

    click.echo("")
    click.echo("Set daily spending limit (protects against runaway costs)")
    daily_budget = _prompt_budget(default=5.0, yes=yes)
    alert_threshold = _prompt_alert_threshold(default=80, yes=yes)
    byok["budget_per_month_usd"] = round(daily_budget * 30.0, 2)
    byok["budget_per_task_usd"] = round(
        min(float(byok.get("budget_per_task_usd", 0.50) or 0.50), daily_budget),
        2,
    )

    click.echo("")
    click.echo("What are you building?")
    click.echo("")
    click.echo("[1] Personal assistant — single user, local only")
    click.echo("[2] Team tool — small team, internal access")
    click.echo("[3] Customer product — public facing, multi-tenant")
    click.echo("[4] Just exploring — defaults for everything")
    click.echo("")
    mode_choice = _prompt_choice(
        "Enter choice [1/2/3/4]:",
        ("1", "2", "3", "4"),
        default="4",
        yes=yes,
    )

    supervised_mode = True
    deployment_mode = "exploring"
    default_tier = "default"
    if mode_choice == "1":
        deployment_mode = "personal_assistant"
        default_tier = "free"
        byok["free_tier_first"] = True
        byok["prefer_cheapest"] = True
    elif mode_choice == "2":
        deployment_mode = "team_tool"
        default_tier = "pro"
        byok["free_tier_first"] = False
        byok["prefer_cheapest"] = False
    elif mode_choice == "3":
        deployment_mode = "customer_product"
        default_tier = "enterprise"
        supervised_mode = False
        byok["free_tier_first"] = False
        byok["prefer_cheapest"] = False
        click.echo("Warning: approval gates remain required for sensitive and financial actions.")

    click.echo("")
    existing_jwt_secret = str(
        os.getenv("ARCHON_JWT_SECRET") or _read_env_value("ARCHON_JWT_SECRET", env_path) or ""
    ).strip()
    if existing_jwt_secret:
        click.echo("✔ JWT secret already configured")
    else:
        generated_secret = secrets.token_hex(32)
        write_env("ARCHON_JWT_SECRET", generated_secret, env_path=env_path)
        click.echo("✔ JWT secret generated and saved to .env")

    config_data = {
        "byok": byok,
        "budget": {
            "daily_limit_usd": daily_budget,
            "alert_threshold_pct": alert_threshold,
        },
        "supervised_mode": supervised_mode,
        "deployment_mode": deployment_mode,
        "default_tier": default_tier,
    }
    _save_onboarding_config(config_data, config_path)
    _load_config(config_path)

    click.echo("")
    click.echo("Running validation...")
    _print_validation_statuses(config_data, ollama_probe=ollama_probe, env_path=env_path)
    validation_exit_code = _run_validation_dry_run(config_data, config_path)
    if validation_exit_code != 0:
        click.echo("⚠ Validation reported issues. Review config.archon.yaml before going live.")

    click.echo("")
    click.echo("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    click.echo("ARCHON is configured and ready.")
    click.echo("")
    click.echo("Your setup:")
    click.echo(f"  Provider:  {provider_summary}")
    click.echo(f"  Budget:    ${daily_budget:.2f}/day")
    mode_summary = (
        "supervised (approval gates on)"
        if supervised_mode
        else "unsupervised (enterprise/public defaults)"
    )
    click.echo(f"  Mode:      {mode_summary}")
    click.echo("")
    click.echo("Next steps:")
    click.echo("  archon serve                  start the server")
    click.echo('  archon task "your question"   run your first task')
    click.echo("  archon dashboard              open Mission Control")
    click.echo("")
    click.echo(f"Config saved to: {config_path}")
    click.echo("Keys saved to:   .env")
    click.echo("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return True


def _resolve_mode(mode: str, prompt: str) -> str:
    if mode != "auto":
        return mode
    lowered = prompt.lower()
    growth_hints = ("lead", "pipeline", "outreach", "growth", "revenue", "churn", "prospect")
    return "growth" if any(hint in lowered for hint in growth_hints) else "debate"


def _resolve_version() -> str:
    return resolve_version()


def _resolve_git_sha() -> str:
    return resolve_git_sha()


def _run_installer_action(action: str, callback: Callable[[], int]) -> None:
    try:
        result = callback()
    except SystemExit as exc:
        code = exc.code
        if code in (None, 0):
            return
        if isinstance(code, int):
            raise click.exceptions.Exit(code) from exc
        raise click.ClickException(f"{action} failed: {code}") from exc

    exit_code = 0 if result is None else int(result)
    if exit_code:
        raise click.exceptions.Exit(exit_code)


def _uninstall_command_impl(home: Path, yes: bool, skip_path: bool, dry_run: bool) -> None:
    if not dry_run and not yes:
        confirmed = click.confirm(
            f"Remove the ARCHON runtime at '{home}'?",
            default=False,
        )
        if not confirmed:
            click.echo("Uninstall cancelled.")
            return
    _run_installer_action(
        "Uninstall",
        lambda: runtime_installer.uninstall(
            install_root=home,
            skip_path=skip_path,
            dry_run=dry_run,
        ),
    )


def _normalize_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip()
    if not normalized:
        return DEFAULT_SERVER_URL
    return normalized.rstrip("/")


def _create_api_headers(
    *,
    token: str | None = None,
    tenant_id: str = "default",
    tier: str = "pro",
) -> dict[str, str]:
    resolved = str(token or "").strip()
    if not resolved:
        resolved = create_tenant_token(tenant_id=tenant_id, tier=tier)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {resolved}"}


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout_s: float = 30.0,
) -> Any:
    response = httpx.request(
        method=method.upper(),
        url=url,
        headers=headers,
        json=json_body,
        timeout=timeout_s,
    )
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def _request_text(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_s: float = 30.0,
) -> str:
    response = httpx.request(
        method=method.upper(),
        url=url,
        headers=headers,
        timeout=timeout_s,
    )
    response.raise_for_status()
    return response.text


def _parse_context(
    context_text: str | None,
    context_file: Path | None,
) -> dict[str, Any]:
    if context_text and context_file is not None:
        raise click.ClickException("Use either --context or --context-file, not both.")
    if context_file is not None:
        with context_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    elif context_text:
        payload = json.loads(context_text)
    else:
        return {}
    if not isinstance(payload, dict):
        raise click.ClickException("Task context must decode to a JSON object.")
    return payload


def _launch_url(url: str) -> None:
    if not click.launch(url):
        raise click.ClickException(f"Could not open browser for {url}")


def _open_web_shell(base_url: str, *, route: str, command_name: str) -> None:
    normalized = _normalize_base_url(base_url)
    health_url = f"{normalized}/health"
    try:
        _request_json("GET", health_url, timeout_s=2.0)
    except (httpx.HTTPError, ValueError) as exc:
        raise click.ClickException(
            "ARCHON server is not reachable at "
            f"{health_url}. Start it with 'archon serve' or pass --base-url to a running "
            f"server, then retry 'archon {command_name}'."
        ) from exc
    _launch_url(f"{normalized}/{route}")


def _run_api_server_with_env(*, host: str, port: int, kill_port: bool = False) -> None:
    previous_host = os.environ.get("ARCHON_HOST")
    previous_port = os.environ.get("ARCHON_PORT")
    previous_kill = os.environ.get("ARCHON_KILL_PORT")
    os.environ["ARCHON_HOST"] = host
    os.environ["ARCHON_PORT"] = str(port)
    if kill_port:
        os.environ["ARCHON_KILL_PORT"] = "1"
    try:
        from archon.interfaces.api.server import run as run_api_server

        run_api_server()
    finally:
        if previous_host is None:
            os.environ.pop("ARCHON_HOST", None)
        else:
            os.environ["ARCHON_HOST"] = previous_host
        if previous_port is None:
            os.environ.pop("ARCHON_PORT", None)
        else:
            os.environ["ARCHON_PORT"] = previous_port
        if previous_kill is None:
            os.environ.pop("ARCHON_KILL_PORT", None)
        else:
            os.environ["ARCHON_KILL_PORT"] = previous_kill


def _parse_prometheus_text(text: str) -> dict[str, list[dict[str, Any]]]:
    metrics: dict[str, list[dict[str, Any]]] = {}
    label_pattern = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"])*)"')
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        sample, _, value_blob = line.rpartition(" ")
        if not sample or not value_blob:
            continue
        try:
            value = float(value_blob)
        except ValueError:
            continue
        labels: dict[str, str] = {}
        if "{" in sample and sample.endswith("}"):
            name, labels_blob = sample[:-1].split("{", 1)
            for key, raw_value in label_pattern.findall(labels_blob):
                labels[key] = (
                    raw_value.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
                )
        else:
            name = sample
        metrics.setdefault(name, []).append({"labels": labels, "value": value})
    return metrics


def _metric_total(
    metrics: dict[str, list[dict[str, Any]]],
    metric_name: str,
    *,
    predicate: Any = None,
) -> float:
    total = 0.0
    for sample in metrics.get(metric_name, []):
        labels = sample.get("labels", {})
        if callable(predicate) and not predicate(labels):
            continue
        total += float(sample.get("value", 0.0) or 0.0)
    return total


def _metric_gauge(metrics: dict[str, list[dict[str, Any]]], metric_name: str) -> float:
    samples = metrics.get(metric_name, [])
    if not samples:
        return 0.0
    return float(samples[-1].get("value", 0.0) or 0.0)


def _top_provider(metrics: dict[str, list[dict[str, Any]]]) -> str:
    totals: dict[str, float] = {}
    for sample in metrics.get("archon_llm_calls_total", []):
        labels = sample.get("labels", {})
        provider = str(labels.get("provider", "unknown"))
        totals[provider] = totals.get(provider, 0.0) + float(sample.get("value", 0.0) or 0.0)
    if not totals:
        return "none"
    provider, count = max(totals.items(), key=lambda item: item[1])
    return f"{provider} ({int(count)})"


def _top_agents(metrics: dict[str, list[dict[str, Any]]], *, limit: int = 3) -> list[str]:
    rows: list[tuple[str, float]] = []
    for sample in metrics.get("archon_agents_recruited_total", []):
        labels = sample.get("labels", {})
        rows.append(
            (str(labels.get("agent_name", "unknown")), float(sample.get("value", 0.0) or 0.0))
        )
    rows.sort(key=lambda item: item[1], reverse=True)
    return [f"{name} ({int(count)})" for name, count in rows[: max(1, int(limit))]]


def _summarize_metrics(text: str) -> dict[str, Any]:
    metrics = _parse_prometheus_text(text)
    total_requests = _metric_total(metrics, "archon_requests_total")
    error_requests = _metric_total(
        metrics,
        "archon_requests_total",
        predicate=lambda labels: str(labels.get("status", "")).startswith("5"),
    )
    error_rate = (error_requests / total_requests * 100.0) if total_requests else 0.0
    return {
        "metrics": metrics,
        "requests_total": total_requests,
        "error_rate": error_rate,
        "active_sessions": _metric_gauge(metrics, "archon_active_sessions"),
        "pending_approvals": _metric_gauge(metrics, "archon_pending_approvals"),
        "top_provider": _top_provider(metrics),
        "top_agents": _top_agents(metrics),
    }


def _render_span_tree(spans: list[dict[str, Any]]) -> list[str]:
    if not spans:
        return ["No spans."]

    by_id = {str(span.get("span_id", "")): span for span in spans}
    children: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []
    for span in spans:
        parent_id = str(span.get("parent_id") or "")
        if parent_id and parent_id in by_id:
            children.setdefault(parent_id, []).append(span)
        else:
            roots.append(span)

    lines: list[str] = []

    def walk(node: dict[str, Any], depth: int) -> None:
        status = str(node.get("status", "ok"))
        name = str(node.get("name", "span"))
        duration = float(node.get("duration_ms", 0.0) or 0.0)
        suffix = ""
        if status != "ok":
            error = str(node.get("error", "")).strip()
            suffix = f" error={error}" if error else " error"
        lines.append(f"{'  ' * depth}- {name} [{status}] {duration:.1f}ms{suffix}")
        for child in children.get(str(node.get("span_id", "")), []):
            walk(child, depth + 1)

    for root in roots:
        walk(root, 0)
    return lines


def _monitor_sleep(seconds: float) -> None:
    time.sleep(max(0.0, float(seconds)))


def _clear_monitor_screen() -> None:
    click.clear()


def _marketplace_period_bounds(period: str) -> tuple[float, float]:
    match = re.fullmatch(r"(\d{4})-(\d{2})", str(period or "").strip())
    if match is None:
        raise click.ClickException("Period must be in YYYY-MM format.")
    year = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        raise click.ClickException("Period must be in YYYY-MM format.")
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start.timestamp(), end.timestamp()


def _marketplace_runtime() -> tuple[
    PartnerRegistry, RevenueShareLedger, PayoutQueue, PayoutOrchestrator
]:
    registry = PartnerRegistry(path=os.getenv("ARCHON_PARTNERS_DB", "archon_partners.sqlite3"))
    revenue_db = os.getenv("ARCHON_MARKETPLACE_REVENUE_DB", "archon_marketplace_revenue.sqlite3")
    queue = PayoutQueue(
        registry=registry,
        ledger=RevenueShareLedger(registry=registry, path=revenue_db),
        approval_gate=ApprovalGate(),
        path=revenue_db,
    )
    orchestrator = PayoutOrchestrator(
        registry=registry,
        ledger=queue.ledger,
        payout_queue=queue,
        approval_gate=queue.approval_gate,
        path=os.getenv("ARCHON_MARKETPLACE_CYCLE_DB", "archon_marketplace_cycles.sqlite3"),
    )
    return registry, queue.ledger, queue, orchestrator


def _cli_auto_approval_sink(gate: ApprovalGate):  # type: ignore[no-untyped-def]
    async def sink(event: dict[str, Any]) -> None:
        if event.get("type") == "approval_required":
            gate.approve(
                str(event.get("request_id", "")),
                approver="archon-cli",
                notes="Approved by interactive CLI operator.",
            )

    return sink


@click.group()
def legacy_cli() -> None:
    """ARCHON CLI."""


legacy_cli.add_command(deploy_group)


@legacy_cli.command("validate")
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
@click.option("--dry-run", is_flag=True, default=False)
def validate_command(config_path: str, dry_run: bool) -> None:
    """Runs validate_config."""

    _load_config(config_path)
    args = ["--config", config_path]
    if dry_run:
        args.append("--dry-run")
    exit_code = int(validate_config_main(args))
    raise click.exceptions.Exit(exit_code)


@legacy_cli.command("onboard")
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
@click.option("--yes", is_flag=True, default=False)
def onboard_command(config_path: str, yes: bool) -> bool:
    """Run the first-run onboarding wizard."""

    return _run_onboarding_wizard(config_path=config_path, yes=yes)


@legacy_cli.command("install")
@click.option(
    "--home",
    default=DEFAULT_INSTALL_ROOT,
    show_default=True,
    type=click.Path(path_type=Path),
)
@click.option(
    "--repo-root",
    default=DEFAULT_INSTALL_REPO_ROOT,
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--dev", is_flag=True, default=False)
@click.option("--skip-path", is_flag=True, default=False)
@click.option("--dry-run", is_flag=True, default=False)
def install_command(
    home: Path,
    repo_root: Path,
    dev: bool,
    skip_path: bool,
    dry_run: bool,
) -> None:
    """Install ARCHON into the dedicated user-local runtime."""

    _run_installer_action(
        "Install",
        lambda: runtime_installer.install(
            repo_root=repo_root,
            install_root=home,
            include_dev=dev,
            skip_path=skip_path,
            dry_run=dry_run,
        ),
    )


@legacy_cli.command("uninstall")
@click.option(
    "--home",
    default=DEFAULT_INSTALL_ROOT,
    show_default=True,
    type=click.Path(path_type=Path),
)
@click.option("--skip-path", is_flag=True, default=False)
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--yes", is_flag=True, default=False)
def uninstall_command(home: Path, skip_path: bool, dry_run: bool, yes: bool) -> None:
    """Uninstall the dedicated ARCHON runtime."""

    _uninstall_command_impl(home=home, yes=yes, skip_path=skip_path, dry_run=dry_run)


@legacy_cli.command("unistall", hidden=True)
@click.option(
    "--home",
    default=DEFAULT_INSTALL_ROOT,
    show_default=True,
    type=click.Path(path_type=Path),
)
@click.option("--skip-path", is_flag=True, default=False)
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--yes", is_flag=True, default=False)
def unistall_command(home: Path, skip_path: bool, dry_run: bool, yes: bool) -> None:
    """Backward-compatible alias for a common misspelling."""

    _uninstall_command_impl(home=home, yes=yes, skip_path=skip_path, dry_run=dry_run)


@legacy_cli.command("serve")
@click.pass_context
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
@click.option("--kill-port", is_flag=True, default=False, help="Terminate the process using host:port before starting.")
def serve_command(
    ctx: click.Context, host: str, port: int, config_path: str, kill_port: bool
) -> None:
    """Start the ARCHON API server."""

    if not Path(config_path).exists():
        click.echo("No config found. Running onboarding wizard...")
        configured = ctx.invoke(onboard_command, config_path=config_path, yes=False)
        if configured is False:
            return
    with _load_env_file():
        _load_config(config_path)
        try:
            _run_api_server_with_env(host=host, port=port, kill_port=kill_port)
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc


@legacy_cli.command("health")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
@click.option("--timeout", "timeout_s", default=5.0, show_default=True, type=float)
def health_command(base_url: str, timeout_s: float) -> None:
    """Check health of a running ARCHON server."""

    printer = _Printer()
    url = f"{_normalize_base_url(base_url)}/health"
    try:
        payload = _request_json("GET", url, timeout_s=timeout_s)
    except (httpx.HTTPError, ValueError) as exc:
        raise click.ClickException(f"Health check failed: {exc}") from exc

    status = str(payload.get("status", "unknown"))
    version = str(payload.get("version", "unknown"))
    git_sha = str(payload.get("git_sha", "") or "").strip()
    db_status = str(payload.get("db_status", "unknown"))
    uptime_s = float(payload.get("uptime_s", 0.0) or 0.0)
    printer.print(f"Status: {status}")
    printer.print(f"Version: {version}")
    if git_sha:
        printer.print(f"Git SHA: {git_sha}")
    printer.print(f"DB: {db_status}")
    printer.print(f"Uptime: {uptime_s:.2f}s")


@legacy_cli.command("metrics")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
@click.option("--timeout", "timeout_s", default=5.0, show_default=True, type=float)
@click.option("--raw", is_flag=True, default=False)
def metrics_command(base_url: str, timeout_s: float, raw: bool) -> None:
    """Fetch and summarize ARCHON metrics."""

    url = f"{_normalize_base_url(base_url)}/metrics"
    try:
        payload = _request_text("GET", url, timeout_s=timeout_s)
    except httpx.HTTPError as exc:
        raise click.ClickException(f"Metrics request failed: {exc}") from exc
    if raw:
        click.echo(payload, nl=False)
        return

    printer = _Printer()
    summary = _summarize_metrics(payload)
    printer.table(
        ["metric", "value"],
        [
            ["requests_total", int(summary["requests_total"])],
            ["error_rate", f"{summary['error_rate']:.2f}%"],
            ["active_sessions", int(summary["active_sessions"])],
            ["pending_approvals", int(summary["pending_approvals"])],
            ["top_provider", summary["top_provider"]],
        ],
    )


@legacy_cli.command("traces")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
@click.option("--timeout", "timeout_s", default=5.0, show_default=True, type=float)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--failed", is_flag=True, default=False)
def traces_command(base_url: str, timeout_s: float, limit: int, failed: bool) -> None:
    """Fetch and render recent ARCHON spans."""

    url = f"{_normalize_base_url(base_url)}/observability/traces"
    try:
        spans = _request_json(
            "GET",
            url,
            json_body=None,
            timeout_s=timeout_s,
            headers=None,
        )
    except httpx.HTTPError as exc:
        raise click.ClickException(f"Traces request failed: {exc}") from exc

    if not isinstance(spans, list):
        raise click.ClickException("Unexpected traces payload.")
    filtered = [span for span in spans if not failed or str(span.get("status", "ok")) != "ok"]
    limited = filtered[-max(1, int(limit)) :]
    for line in _render_span_tree(limited):
        click.echo(line)


@legacy_cli.command("monitor")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
@click.option("--timeout", "timeout_s", default=5.0, show_default=True, type=float)
@click.option("--interval", default=5.0, show_default=True, type=float)
def monitor_command(base_url: str, timeout_s: float, interval: float) -> None:
    """Render a live terminal monitor for ARCHON."""

    printer = _Printer()
    normalized_base = _normalize_base_url(base_url)
    previous_total: float | None = None
    previous_ts: float | None = None
    try:
        while True:
            try:
                health = _request_json("GET", f"{normalized_base}/health", timeout_s=timeout_s)
                metrics_text = _request_text(
                    "GET",
                    f"{normalized_base}/metrics",
                    timeout_s=timeout_s,
                )
                spans = _request_json(
                    "GET",
                    f"{normalized_base}/observability/traces",
                    timeout_s=timeout_s,
                )
            except (httpx.HTTPError, ValueError) as exc:
                raise click.ClickException(
                    "ARCHON server is not reachable at "
                    f"{normalized_base}. Start it with 'archon serve' or pass --base-url "
                    "to a running server, then retry 'archon monitor'."
                ) from exc
            summary = _summarize_metrics(metrics_text)
            now = time.monotonic()
            req_per_s = 0.0
            if previous_total is not None and previous_ts is not None and now > previous_ts:
                req_per_s = max(
                    0.0, (summary["requests_total"] - previous_total) / (now - previous_ts)
                )
            previous_total = float(summary["requests_total"])
            previous_ts = now
            _clear_monitor_screen()
            status = "ok" if str(health.get("status", "unknown")) == "ok" else "down"
            printer.print(f"ARCHON monitor status={status}")
            printer.print(f"req/s: {req_per_s:.2f}")
            printer.print(f"error%: {summary['error_rate']:.2f}")
            printer.print(f"active_sessions: {int(summary['active_sessions'])}")
            printer.print(f"pending_approvals: {int(summary['pending_approvals'])}")
            printer.print(
                "top_agents: "
                + (", ".join(summary["top_agents"]) if summary["top_agents"] else "none")
            )
            printer.print("last_spans:")
            rendered = _render_span_tree(list(spans)[-5:] if isinstance(spans, list) else [])
            for line in rendered:
                printer.print(line)
            _monitor_sleep(interval)
    except KeyboardInterrupt:
        printer.print("Monitor stopped.")


@legacy_cli.command("task")
@click.argument("goal")
@click.option("--mode", type=click.Choice(["debate", "growth", "auto"]), default="auto")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
@click.option("--tenant-id", default="default", show_default=True)
@click.option(
    "--tier", type=click.Choice(["free", "pro", "enterprise"]), default="pro", show_default=True
)
@click.option("--token", default="", show_default=False)
@click.option("--context", "context_text", default="", show_default=False)
@click.option(
    "--context-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
@click.option("--timeout", "timeout_s", default=60.0, show_default=True, type=float)
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
    """Send one task to the running ARCHON API."""

    printer = _Printer()
    effective_mode = _resolve_mode(mode, goal)
    context = _parse_context(context_text or None, context_file)
    headers = _create_api_headers(token=token or None, tenant_id=tenant_id, tier=tier)
    url = f"{_normalize_base_url(base_url)}/v1/tasks"
    body = {
        "goal": goal,
        "mode": effective_mode,
        "context": context,
    }
    try:
        payload = _request_json(
            "POST",
            url,
            headers=headers,
            json_body=body,
            timeout_s=timeout_s,
        )
    except (httpx.HTTPError, ValueError) as exc:
        raise click.ClickException(f"Task request failed: {exc}") from exc

    printer.print(f"[bold]Mode:[/bold] {payload.get('mode', effective_mode)}")
    printer.print(str(payload.get("final_answer", "")))
    printer.print(f"Confidence: {int(payload.get('confidence', 0) or 0)}%")
    budget = payload.get("budget") or {}
    printer.print(f"Budget spent: ${float(budget.get('spent_usd', 0.0) or 0.0):.4f}")


@legacy_cli.command("dashboard")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
def dashboard_command(base_url: str) -> None:
    """Open the Mission Control dashboard in the default browser."""

    _open_web_shell(base_url, route="dashboard", command_name="dashboard")


@legacy_cli.command("studio")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
def studio_command(base_url: str) -> None:
    """Open ARCHON Studio in the default browser."""

    _open_web_shell(base_url, route="studio", command_name="studio")


@legacy_cli.command("debate")
@click.argument("question")
@click.option("--mode", type=click.Choice(["debate", "growth", "auto"]), default="auto")
@click.option("--budget", type=float, default=None)
@click.option("--live-providers", is_flag=True, default=False)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def debate_command(
    question: str,
    mode: str,
    budget: float | None,
    live_providers: bool,
    config_path: str,
) -> None:
    """Run ARCHON debate/growth orchestration for a question."""

    printer = _Printer()
    config = _load_config(config_path)
    if budget is not None:
        config.byok.budget_per_task_usd = float(budget)
    effective_mode = _resolve_mode(mode, question)

    async def _run() -> None:
        orchestrator = Orchestrator(config=config, live_provider_calls=live_providers)
        try:
            result = await orchestrator.execute(goal=question, mode=effective_mode)  # type: ignore[arg-type]
            printer.print(f"[bold]Mode:[/bold] {result.mode}")
            printer.print(result.final_answer)
            printer.print(f"Confidence: {result.confidence}%")
            printer.print(f"Budget spent: ${result.budget.get('spent_usd', 0):.4f}")
        finally:
            await orchestrator.aclose()

    asyncio.run(_run())


@legacy_cli.command("tui")
@click.option("--mode", type=click.Choice(["debate", "growth", "auto"]), default="auto")
@click.option("--budget", type=float, default=None)
@click.option("--live-providers", is_flag=True, default=False)
@click.option("--context", "context_text", default="", show_default=False)
@click.option(
    "--context-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def tui_command(
    mode: str,
    budget: float | None,
    live_providers: bool,
    context_text: str,
    context_file: Path | None,
    config_path: str,
) -> None:
    """Launch the interactive ARCHON agentic terminal UI."""

    config = (
        _load_config(config_path)
        if Path(config_path).exists()
        else load_archon_config("__wizard_defaults__.yaml")
    )
    if budget is not None:
        config.byok.budget_per_task_usd = float(budget)
    effective_live_providers = live_providers or _should_default_tui_to_live(config)
    context = _parse_context(context_text or None, context_file)
    onboarding = OnboardingCallbacks(
        default_byok_config=_default_byok_config,
        probe_ollama=_probe_ollama,
        validate_openrouter_key=_validate_openrouter_key,
        validate_openai_key=_validate_openai_key,
        validate_anthropic_key=_validate_anthropic_key,
        save_config=_save_onboarding_config,
        run_validation=_run_validation_dry_run,
        read_env_value=_read_env_value,
        write_env=write_env,
        load_config=_load_config,
    )
    asyncio.run(
        run_agentic_tui(
            config=config,
            initial_mode=mode,
            live_provider_calls=effective_live_providers,
            initial_context=context,
            config_path=config_path,
            onboarding=onboarding,
            show_launcher=True,
        )
    )


@legacy_cli.command("run")
@click.argument("workflow_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--live-providers", is_flag=True, default=False)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def run_command(workflow_file: Path, dry_run: bool, live_providers: bool, config_path: str) -> None:
    """Run workflow YAML."""

    printer = _Printer()
    config = _load_config(config_path)
    with workflow_file.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise click.ClickException("Workflow file must contain a YAML object.")

    if dry_run:
        name = str(payload.get("name", workflow_file.name))
        steps = payload.get("steps", [])
        printer.print(f"Dry-run workflow: {name}")
        printer.print(f"Steps: {len(steps) if isinstance(steps, list) else 0}")
        return

    goal = str(payload.get("goal", f"Run workflow from {workflow_file.name}"))
    mode = str(payload.get("mode", "debate")).lower()
    if mode not in {"debate", "growth"}:
        mode = "debate"

    async def _run() -> None:
        orchestrator = Orchestrator(config=config, live_provider_calls=live_providers)
        try:
            result = await orchestrator.execute(goal=goal, mode=mode)  # type: ignore[arg-type]
            printer.print(result.final_answer)
        finally:
            await orchestrator.aclose()

    asyncio.run(_run())


@legacy_cli.group("memory")
def memory_group() -> None:
    """Memory operations."""


@memory_group.command("search")
@click.argument("query")
@click.option("--tenant", "tenant_id", default="default", show_default=True)
@click.option("--top-k", default=10, show_default=True, type=int)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def memory_search_command(query: str, tenant_id: str, top_k: int, config_path: str) -> None:
    """Search memory."""

    _load_config(config_path)
    store = MemoryStore()
    printer = _Printer()
    try:
        results = store.search(query=query, tenant_id=tenant_id, top_k=top_k)
    finally:
        store.close()

    rows = []
    for row in results:
        rows.append(
            [
                row.memory.memory_id,
                f"{row.similarity:.3f}",
                row.memory.role,
                row.memory.content[:70],
            ]
        )
    if not rows:
        printer.print("No memory results.")
        return
    printer.table(["memory_id", "similarity", "role", "content"], rows)


@legacy_cli.group("peers")
def peers_group() -> None:
    """Federation peer operations."""


@peers_group.command("list")
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def peers_list_command(config_path: str) -> None:
    """List known peers."""

    _load_config(config_path)
    printer = _Printer()

    async def _run() -> list[Peer]:
        registry = PeerRegistry()
        try:
            return await registry.discover(None)
        finally:
            await registry.aclose()

    peers = asyncio.run(_run())
    rows = [
        [peer.peer_id, peer.address, ",".join(peer.capabilities), peer.version] for peer in peers
    ]
    if not rows:
        printer.print("No peers found.")
        return
    printer.table(["peer_id", "address", "capabilities", "version"], rows)


@peers_group.command("add")
@click.argument("address")
@click.option("--capability", "capabilities", multiple=True)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def peers_add_command(address: str, capabilities: tuple[str, ...], config_path: str) -> None:
    """Add one peer."""

    _load_config(config_path)
    printer = _Printer()
    now = time.time()
    peer = Peer(
        peer_id=f"peer-{uuid.uuid4().hex[:8]}",
        address=address,
        public_key="unknown",
        last_seen=now,
        capabilities=list(capabilities) if capabilities else ["debate"],
        version="unknown",
    )

    async def _run() -> Peer:
        registry = PeerRegistry()
        try:
            return await registry.register(peer)
        finally:
            await registry.aclose()

    registered = asyncio.run(_run())
    printer.print(f"Peer added: {registered.peer_id} @ {registered.address}")


@legacy_cli.group("redteam")
def redteam_group() -> None:
    """Automated red-team regression operations."""


@redteam_group.command("regression")
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
@click.option(
    "--output-dir",
    default="artifacts/redteam",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--payloads-per-vector", default=1, show_default=True, type=int)
@click.option("--live-providers", is_flag=True, default=False)
def redteam_regression_command(
    config_path: str,
    output_dir: Path,
    payloads_per_vector: int,
    live_providers: bool,
) -> None:
    """Run a deterministic red-team regression sweep and export artifacts."""

    outcome = asyncio.run(
        _run_redteam_regression(
            config_path=config_path,
            output_dir=output_dir,
            payloads_per_vector=payloads_per_vector,
            live_provider_calls=live_providers,
        )
    )
    printer = _Printer()
    printer.print(f"Regression scan: {outcome.report.scan_id}")
    printer.print(f"Payloads: {outcome.report.total_payloads}")
    printer.print(f"Findings: {len(outcome.report.findings)}")
    printer.print(f"Markdown report: {outcome.markdown_path}")
    printer.print(f"JSON report: {outcome.json_path}")
    if outcome.failed_categories:
        printer.print(
            "Failed categories: "
            + ", ".join(
                f"{category}={value:.3f}"
                for category, value in sorted(outcome.failed_categories.items())
            )
        )
    if outcome.blocking_findings:
        printer.print(
            "Blocking findings: "
            + ", ".join(
                f"{finding.agent_name}:{finding.failure_mode}:{finding.severity}"
                for finding in outcome.blocking_findings
            )
        )
    if not outcome.passed:
        raise click.ClickException("Red-team regression failed.")


@legacy_cli.group("payouts")
def payouts_group() -> None:
    """Marketplace payout operations."""


@payouts_group.command("list")
def payouts_list_command() -> None:
    """List pending marketplace payouts."""

    printer = _Printer()
    registry, _ledger, queue, _orchestrator = _marketplace_runtime()
    rows = []
    try:
        for payout in queue.list_pending():
            partner = registry.get(payout.partner_id)
            rows.append(
                [
                    payout.payout_id,
                    partner.name if partner is not None else payout.partner_id,
                    f"${payout.amount_usd:.2f}",
                    payout.status,
                ]
            )
    finally:
        asyncio.run(queue.aclose())
    if not rows:
        printer.print("No pending payouts.")
        return
    printer.table(["payout_id", "partner", "amount", "status"], rows)


@payouts_group.command("run")
@click.option("--period", "period_text", required=True)
def payouts_run_command(period_text: str) -> None:
    """Run one marketplace payout cycle for the provided month."""

    printer = _Printer()
    _start, _end = _marketplace_period_bounds(period_text)
    registry, ledger, queue, orchestrator = _marketplace_runtime()
    del registry, ledger

    async def _run() -> None:
        try:
            result = await orchestrator.run_cycle(
                _start,
                _end,
                event_sink=_cli_auto_approval_sink(queue.approval_gate),
            )
        finally:
            await queue.aclose()
        printer.print(f"Cycle: {result.cycle_id}")
        printer.print(f"Partners paid: {result.partners_paid}")
        printer.print(f"Partners skipped: {result.partners_skipped}")
        printer.print(f"Total paid: ${result.total_paid_usd:.2f}")
        if result.failures:
            printer.print("Failures: " + ", ".join(result.failures))

    asyncio.run(_run())


@payouts_group.command("status")
@click.argument("payout_id")
def payouts_status_command(payout_id: str) -> None:
    """Show one payout record and transfer status."""

    printer = _Printer()
    registry, _ledger, queue, _orchestrator = _marketplace_runtime()
    del registry
    try:
        payout = queue.get(payout_id)
    finally:
        asyncio.run(queue.aclose())
    if payout is None:
        raise click.ClickException(f"Payout '{payout_id}' not found.")
    printer.print(f"Payout: {payout.payout_id}")
    printer.print(f"Partner: {payout.partner_id}")
    printer.print(f"Status: {payout.status}")
    printer.print(f"Amount: ${payout.amount_usd:.2f}")
    if payout.transfer_id:
        printer.print(f"Transfer ID: {payout.transfer_id}")


@legacy_cli.command("earnings")
@click.argument("partner_id")
@click.option("--period", "period_text", required=True)
def earnings_command(partner_id: str, period_text: str) -> None:
    """Show developer earnings for one partner and month."""

    printer = _Printer()
    period_start, period_end = _marketplace_period_bounds(period_text)
    registry, ledger, queue, _orchestrator = _marketplace_runtime()
    del registry, _orchestrator
    try:
        earnings = ledger.aggregate_developer(partner_id, period_start, period_end)
    finally:
        asyncio.run(queue.aclose())
    printer.print(f"Partner: {earnings.partner_id}")
    printer.print(f"Period: {period_text}")
    printer.print(f"Gross: ${earnings.gross_usd:.2f}")
    printer.print(f"Developer total: ${earnings.developer_usd:.2f}")
    printer.print(f"ARCHON share: ${earnings.archon_usd:.2f}")


@legacy_cli.group("token")
def token_group() -> None:
    """Tenant token operations."""


@token_group.command("create")
@click.option("--tenant-id", required=True)
@click.option("--tier", type=click.Choice(["free", "pro", "enterprise"]), required=True)
@click.option("--expires-in", default=3600, show_default=True, type=int)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def token_create_command(tenant_id: str, tier: str, expires_in: int, config_path: str) -> None:
    """Create signed tenant JWT."""

    _load_config(config_path)
    token = create_tenant_token(tenant_id=tenant_id, tier=tier, expires_in_seconds=expires_in)  # type: ignore[arg-type]
    click.echo(token)


@legacy_cli.command("version")
def version_command() -> None:
    """Print ARCHON version + git sha."""

    click.echo(f"ARCHON {_resolve_version()} (git {_resolve_git_sha()})")


async def _run_redteam_regression(
    *,
    config_path: str,
    output_dir: Path,
    payloads_per_vector: int,
    live_provider_calls: bool,
):
    config = _load_config(config_path)
    orchestrator = Orchestrator(config=config, live_provider_calls=live_provider_calls)
    try:
        runner = RegressionRunner(orchestrator=orchestrator)
        return await runner.run(
            output_dir=output_dir,
            payloads_per_vector=payloads_per_vector,
        )
    finally:
        await orchestrator.aclose()


def _build_root_cli() -> click.Group:
    from archon.cli.main import build_cli

    return build_cli(sys.modules[__name__])


cli = _build_root_cli()


def main() -> None:
    """Entry point for `python -m archon.archon_cli`."""

    cli(prog_name="archon")


if __name__ == "__main__":
    main()
