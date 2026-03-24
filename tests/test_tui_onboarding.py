"""Tests for the TUI launcher and setup wizard flows."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest

from archon.config import ArchonConfig
from archon.interfaces.cli import tui_onboarding


def test_run_launcher_updates_mode() -> None:
    choices = iter(["mode", "debate", "start"])

    async def fake_choose_menu_option(**_: Any) -> str:
        return next(choices)

    original = tui_onboarding.choose_menu_option
    tui_onboarding.choose_menu_option = fake_choose_menu_option
    try:
        result = asyncio.run(
            tui_onboarding.run_launcher(
                config=ArchonConfig(),
                config_path="config.archon.yaml",
                mode="auto",
                onboarding=None,
            )
        )
    finally:
        tui_onboarding.choose_menu_option = original

    assert result.start is True
    assert result.mode == "debate"
    assert any(note["body"] == "Default mode set to debate." for note in result.notes)


def test_run_setup_wizard_saves_real_config_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: dict[str, Any] = {}
    env_writes: list[tuple[str, str]] = []
    sentinel_config = ArchonConfig()
    choices = iter(["continue", "free", "5", "80", "team"])
    monkeypatch.delenv("ARCHON_JWT_SECRET", raising=False)

    async def fake_choose_menu_option(**_: Any) -> str:
        return next(choices)

    async def fake_prompt_text(*_: Any, **__: Any) -> str:
        return ""

    callbacks = tui_onboarding.OnboardingCallbacks(
        default_byok_config=lambda: {"budget_per_task_usd": 0.5},
        probe_ollama=lambda timeout_s: {"reachable": True, "models": ["llama3.2"]},
        validate_openrouter_key=lambda key, timeout_s: True,
        validate_openai_key=lambda key, timeout_s: True,
        validate_anthropic_key=lambda key, timeout_s: True,
        save_config=lambda config_data, config_path: saved.update(
            {"config_data": config_data, "config_path": config_path}
        ),
        run_validation=lambda config_data, config_path: 0,
        read_env_value=lambda key, env_path: None,
        write_env=lambda key, value, env_path: env_writes.append((key, value)),
        load_config=lambda config_path: sentinel_config,
    )
    original_choose = tui_onboarding.choose_menu_option
    original_prompt = tui_onboarding.prompt_text
    tui_onboarding.choose_menu_option = fake_choose_menu_option
    tui_onboarding.prompt_text = fake_prompt_text
    try:
        config, summary = asyncio.run(
            tui_onboarding.run_setup_wizard(
                config_path=str(Path("config.archon.yaml")),
                onboarding=callbacks,
                current_config=ArchonConfig(),
            )
        )
    finally:
        tui_onboarding.choose_menu_option = original_choose
        tui_onboarding.prompt_text = original_prompt

    assert config is sentinel_config
    assert saved["config_path"] == "config.archon.yaml"
    assert saved["config_data"]["byok"]["primary"] == "ollama"
    assert saved["config_data"]["budget"] == {
        "daily_limit_usd": 5.0,
        "alert_threshold_pct": 80,
    }
    assert saved["config_data"]["deployment_mode"] == "team_tool"
    assert saved["config_data"]["default_tier"] == "pro"
    assert saved["config_data"]["supervised_mode"] is True
    assert env_writes[0][0] == "ARCHON_JWT_SECRET"
    assert os.getenv("ARCHON_JWT_SECRET") is None
    assert "Connection: ollama (local models)" in summary
