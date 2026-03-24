"""Launcher and onboarding flows for the ARCHON TUI."""

from __future__ import annotations

import asyncio
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import click

from archon.config import ArchonConfig
from archon.interfaces.cli.tui_input import read_key, supports_raw_keys
from archon.interfaces.cli.tui_render import render_menu_screen

_PROVIDER_KEY_URLS = {
    "anthropic": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
    "openrouter": "https://openrouter.ai/keys",
}


@dataclass(slots=True)
class MenuOption:
    key: str
    label: str
    description: str


@dataclass(slots=True)
class LauncherResult:
    start: bool
    config: ArchonConfig
    mode: str
    notes: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class OnboardingCallbacks:
    default_byok_config: Callable[[], dict[str, Any]]
    probe_ollama: Callable[[float], dict[str, Any]]
    validate_openrouter_key: Callable[[str, float], bool]
    validate_openai_key: Callable[[str, float], bool]
    validate_anthropic_key: Callable[[str, float], bool]
    save_config: Callable[[dict[str, Any], str], None]
    run_validation: Callable[[dict[str, Any], str], int]
    read_env_value: Callable[[str, str | Path], str | None]
    write_env: Callable[[str, str, str | Path], None]
    load_config: Callable[[str], ArchonConfig]


async def run_launcher(
    *,
    config: ArchonConfig,
    config_path: str,
    mode: str,
    onboarding: OnboardingCallbacks | None,
) -> LauncherResult:
    """Run the startup launcher and optional setup wizard.

    Example:
        >>> result = LauncherResult(start=True, config=ArchonConfig())
        >>> result.start
        True
    """

    notes: list[dict[str, str]] = []
    current_config = config
    current_mode = mode
    while True:
        options = [
            MenuOption("start", "Start agent shell", "Open the ARCHON transcript workspace."),
            MenuOption(
                "setup",
                "Run setup wizard",
                "Configure connections, budgets, and launch defaults.",
            ),
            MenuOption("mode", f"Change mode ({current_mode})", "Switch the default routing mode."),
            MenuOption("quit", "Quit", "Exit before starting the shell."),
        ]
        choice = await choose_menu_option(
            title="Launch ARCHON",
            body=[
                f"Config path: {config_path}",
                f"Config detected: {'yes' if Path(config_path).exists() else 'no'}",
                f"Mode: {current_mode}",
                "",
                "Use Up/Down and Enter. If raw terminal input is unavailable, enter the option number.",
            ],
            options=options,
        )
        if choice == "start":
            return LauncherResult(
                start=True,
                config=current_config,
                mode=current_mode,
                notes=notes,
            )
        if choice == "quit":
            return LauncherResult(
                start=False,
                config=current_config,
                mode=current_mode,
                notes=notes,
            )
        if choice == "mode":
            current_mode = await choose_menu_option(
                title="Choose default mode",
                body=["Select how ARCHON should route new prompts before the chat starts."],
                options=[
                    MenuOption("debate", "Debate", "Always use the adversarial analysis swarm."),
                ],
            )
            notes.append(
                {
                    "title": "Launcher",
                    "body": f"Default mode set to {current_mode}.",
                    "tone": "system",
                }
            )
            continue
        if choice == "setup" and onboarding is not None:
            current_config, summary = await run_setup_wizard(
                config_path=config_path,
                onboarding=onboarding,
                current_config=current_config,
            )
            notes.append({"title": "Setup complete", "body": summary, "tone": "system"})


async def run_setup_wizard(
    *,
    config_path: str,
    onboarding: OnboardingCallbacks,
    current_config: ArchonConfig,
) -> tuple[ArchonConfig, str]:
    """Run the guided setup wizard and persist ARCHON config/env state."""

    proceed = await choose_menu_option(
        title="Security",
        body=[
            "ARCHON can call models, store knowledge, and gate sensitive actions.",
            "Use tenant tokens and confirmation gates before exposing it beyond one trusted operator.",
            "All new external actions still require confirmation where policy says so.",
        ],
        options=[
            MenuOption("continue", "Continue setup", "Proceed into connection and budget setup."),
            MenuOption("cancel", "Cancel", "Return to the launcher without saving."),
        ],
    )
    if proceed == "cancel":
        return current_config, "Setup cancelled."

    stack = await choose_menu_option(
        title="Connection stack",
        body=["Choose the default connection strategy for ARCHON."],
        options=[
            MenuOption("free", "Free", "Ollama local-first with optional OpenRouter fallback."),
            MenuOption("pro", "Pro", "Anthropic / OpenAI cloud setup."),
            MenuOption("custom", "Custom", "Keep defaults and edit config manually later."),
        ],
    )
    budget_profile = await choose_menu_option(
        title="Daily budget",
        body=["Pick a default daily ceiling. You can change this later in config."],
        options=[
            MenuOption("1", "$1/day", "Conservative local-first usage."),
            MenuOption("5", "$5/day", "Recommended for mixed development usage."),
            MenuOption("20", "$20/day", "Higher ceiling for heavier sessions."),
            MenuOption("custom", "Custom", "Enter an exact USD value."),
        ],
    )
    daily_budget = (
        await prompt_float("Daily budget in USD", default=5.0, minimum=0.1, maximum=1000.0)
        if budget_profile == "custom"
        else float(budget_profile)
    )
    alert_profile = await choose_menu_option(
        title="Alert threshold",
        body=["Choose when ARCHON should consider the daily budget close to exhausted."],
        options=[
            MenuOption("70", "70%", "Warn early for tight control."),
            MenuOption("80", "80%", "Recommended default."),
            MenuOption("90", "90%", "Warn late and prioritize continuity."),
        ],
    )
    deployment_mode = await choose_menu_option(
        title="Launch mode",
        body=["Tell ARCHON what you are building so defaults match the risk profile."],
        options=[
            MenuOption("personal", "Personal assistant", "Single-user, cheapest defaults."),
            MenuOption("team", "Team tool", "Small internal team."),
            MenuOption("customer", "Customer product", "Public or multi-tenant launch."),
            MenuOption("explore", "Just exploring", "Safe defaults for experimentation."),
        ],
    )

    env_path = Path(".env")
    byok = onboarding.default_byok_config()
    provider_summary, probe_detail = await _configure_stack(stack, byok, env_path, onboarding)
    byok["budget_per_month_usd"] = round(daily_budget * 30.0, 2)
    byok["budget_per_task_usd"] = round(
        min(float(byok.get("budget_per_task_usd", 0.50) or 0.50), daily_budget),
        2,
    )

    supervised_mode = deployment_mode != "customer"
    default_tier = {
        "personal": "free",
        "team": "pro",
        "customer": "enterprise",
        "explore": "default",
    }[deployment_mode]
    byok["free_tier_first"] = deployment_mode in {"personal", "explore"} and stack != "pro"
    byok["prefer_cheapest"] = deployment_mode in {"personal", "explore"} and stack != "pro"

    if not str(
        os.getenv("ARCHON_JWT_SECRET")
        or onboarding.read_env_value("ARCHON_JWT_SECRET", env_path)
        or ""
    ).strip():
        generated_secret = secrets.token_hex(32)
        onboarding.write_env("ARCHON_JWT_SECRET", generated_secret, env_path)

    config_data = {
        "byok": byok,
        "budget": {
            "daily_limit_usd": round(daily_budget, 2),
            "alert_threshold_pct": int(alert_profile),
        },
        "supervised_mode": supervised_mode,
        "deployment_mode": {
            "personal": "personal_assistant",
            "team": "team_tool",
            "customer": "customer_product",
            "explore": "exploring",
        }[deployment_mode],
        "default_tier": default_tier,
    }
    onboarding.save_config(config_data, config_path)
    validation_exit_code = onboarding.run_validation(config_data, config_path)
    summary = "\n".join(
        [
            f"Connection: {provider_summary}",
            f"Budget: ${daily_budget:.2f}/day | alert {int(alert_profile)}%",
            f"Mode: {'supervised' if supervised_mode else 'enterprise/public defaults'}",
            f"Probe: {probe_detail}",
            "Validation: passed" if validation_exit_code == 0 else "Validation: review needed",
        ]
    )
    return onboarding.load_config(config_path), summary


async def choose_menu_option(
    *,
    title: str,
    body: list[str],
    options: list[MenuOption],
) -> str:
    """Render and resolve a single-select menu."""

    if not options:
        raise ValueError("Menu requires at least one option.")
    if not supports_raw_keys():
        return await _choose_menu_option_fallback(title=title, body=body, options=options)
    index = 0
    while True:
        click.echo(
            render_menu_screen(title=title, body=body, options=options, selected_index=index),
            nl=False,
        )
        key = await read_key()
        if key == "up":
            index = (index - 1) % len(options)
        elif key == "down":
            index = (index + 1) % len(options)
        elif key == "enter":
            return options[index].key
        elif key == "escape":
            return options[-1].key


async def prompt_text(label: str, *, default: str = "", secret: bool = False) -> str:
    """Prompt for one line of text without logging sensitive values."""

    return await asyncio.to_thread(_prompt_text_sync, label, default, secret)


async def prompt_float(
    label: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    """Prompt for a bounded float value."""

    while True:
        value = await prompt_text(label, default=f"{default:.2f}")
        try:
            parsed = round(float(value), 2)
        except ValueError:
            click.echo(f"Enter a number between {minimum:.2f} and {maximum:.2f}.")
            continue
        if minimum <= parsed <= maximum:
            return parsed
        click.echo(f"Enter a number between {minimum:.2f} and {maximum:.2f}.")


async def _choose_menu_option_fallback(
    *,
    title: str,
    body: list[str],
    options: list[MenuOption],
) -> str:
    click.echo(
        render_menu_screen(title=title, body=body, options=options, selected_index=0), nl=False
    )
    while True:
        value = (await asyncio.to_thread(click.prompt, "Select option number", default="1")).strip()
        if value.isdigit():
            index = int(value) - 1
            if 0 <= index < len(options):
                return options[index].key
        click.echo("Enter a valid option number.")


def _prompt_text_sync(label: str, default: str, secret: bool) -> str:
    value = click.prompt(label, default=default, show_default=bool(default), hide_input=secret)
    return str(value).strip()


def _provider_key_url(provider: str) -> str:
    return _PROVIDER_KEY_URLS.get(provider, "")


def _mask_key(value: str) -> str:
    cleaned = str(value or "").strip()
    if len(cleaned) <= 6:
        return "*" * len(cleaned)
    return f"{cleaned[:2]}...{cleaned[-4:]}"


async def _await_login(
    provider: str,
    *,
    env_path: Path,
    onboarding: OnboardingCallbacks,
) -> None:
    url = _provider_key_url(provider)
    if not url:
        return
    click.echo(f"Key portal: {url}")
    env_name = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(provider, "")
    existing = ""
    if env_name:
        existing = str(
            os.getenv(env_name) or onboarding.read_env_value(env_name, env_path) or ""
        ).strip()
    if existing:
        return
    await prompt_text("Press Enter once logged in (or press Enter to skip)", default="")


async def _validate_key_with_spinner(
    label: str,
    validator: Callable[[str, float], bool],
    key: str,
) -> bool:
    frames = "|/-\\"
    stop = asyncio.Event()

    async def _spin() -> None:
        index = 0
        while not stop.is_set():
            click.echo(f"\r{label} {frames[index % len(frames)]}", nl=False)
            await asyncio.sleep(0.12)
            index += 1

    spinner_task = asyncio.create_task(_spin())
    try:
        result = await asyncio.to_thread(validator, key, 5.0)
    finally:
        stop.set()
        await spinner_task
    status = "ok" if result else "failed"
    click.echo(f"\r{label} {status}".ljust(48))
    return bool(result)


async def _configure_stack(
    stack: str,
    byok: dict[str, Any],
    env_path: Path,
    onboarding: OnboardingCallbacks,
) -> tuple[str, str]:
    if stack == "custom":
        return "custom (edit config manually)", "manual configuration"
    if stack == "free":
        probe = onboarding.probe_ollama(2.0)
        await _await_login("openrouter", env_path=env_path, onboarding=onboarding)
        openrouter_key = await prompt_text("OpenRouter API key (optional)", default="", secret=True)
        if openrouter_key:
            click.echo(f"OpenRouter key captured: {_mask_key(openrouter_key)}")
            ok = await _validate_key_with_spinner(
                "Authenticating OpenRouter key",
                onboarding.validate_openrouter_key,
                openrouter_key,
            )
            if ok:
                click.echo("OpenRouter key authenticated.")
                onboarding.write_env("OPENROUTER_API_KEY", openrouter_key, env_path)
            else:
                click.echo("OpenRouter key authentication failed.")
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
        models = ", ".join(probe.get("models", [])) or "none detected"
        return (
            "ollama + openrouter fallback" if openrouter_key else "ollama (local models)",
            f"Ollama {'reachable' if probe.get('reachable') else 'unreachable'} | models: {models}",
        )

    await _await_login("anthropic", env_path=env_path, onboarding=onboarding)
    anthropic_key = await prompt_text("Anthropic API key (optional)", default="", secret=True)
    await _await_login("openai", env_path=env_path, onboarding=onboarding)
    openai_key = await prompt_text("OpenAI API key (optional)", default="", secret=True)
    if anthropic_key:
        click.echo(f"Anthropic key captured: {_mask_key(anthropic_key)}")
        ok = await _validate_key_with_spinner(
            "Authenticating Anthropic key",
            onboarding.validate_anthropic_key,
            anthropic_key,
        )
        if ok:
            click.echo("Anthropic key authenticated.")
            onboarding.write_env("ANTHROPIC_API_KEY", anthropic_key, env_path)
        else:
            click.echo("Anthropic key authentication failed.")
    if openai_key:
        click.echo(f"OpenAI key captured: {_mask_key(openai_key)}")
        ok = await _validate_key_with_spinner(
            "Authenticating OpenAI key",
            onboarding.validate_openai_key,
            openai_key,
        )
        if ok:
            click.echo("OpenAI key authenticated.")
            onboarding.write_env("OPENAI_API_KEY", openai_key, env_path)
        else:
            click.echo("OpenAI key authentication failed.")
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
        return "anthropic + openai", "Cloud keys configured"
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
        return "anthropic", "Anthropic key configured"
    if openai_key:
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
        return "openai", "OpenAI key configured"
    probe = onboarding.probe_ollama(2.0)
    byok.update(
        {
            "primary": "ollama",
            "coding": "ollama",
            "vision": "ollama",
            "fast": "ollama",
            "embedding": "ollama",
            "fallback": "ollama",
            "prefer_cheapest": True,
            "free_tier_first": True,
        }
    )
    return (
        "ollama fallback",
        f"No cloud keys provided; Ollama {'reachable' if probe.get('reachable') else 'unreachable'}",
    )
