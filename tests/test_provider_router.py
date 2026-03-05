"""Unit tests for provider resolution and simulated invocation."""

from __future__ import annotations

import asyncio

import pytest

from archon.config import ArchonConfig
from archon.core.cost_governor import CostGovernor
from archon.providers.router import ProviderRouter, ProviderUnavailableError


def test_resolve_provider_uses_primary_when_key_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    config = ArchonConfig()
    router = ProviderRouter(config=config)

    selection = router.resolve_provider(role="primary")
    assert selection.provider == "anthropic"
    assert selection.model == "claude-sonnet-4-5"
    assert selection.source == "built_in"


def test_resolve_provider_falls_back_when_primary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    config = ArchonConfig()
    router = ProviderRouter(config=config)

    selection = router.resolve_provider(role="primary")
    assert selection.provider == "openrouter"
    assert selection.model == config.byok.openrouter_fallback_chain[0]


def test_resolve_provider_raises_when_no_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    config = ArchonConfig()
    router = ProviderRouter(config=config)

    with pytest.raises(ProviderUnavailableError):
        router.resolve_provider(role="primary")


def test_invoke_simulation_charges_cost_governor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    governor = CostGovernor(default_budget_usd=1.0)
    governor.start_task("task-1")

    config = ArchonConfig()
    router = ProviderRouter(config=config, cost_governor=governor, live_mode=False)

    response = asyncio.run(
        router.invoke(role="coding", prompt="Write a SQL query", task_id="task-1")
    )
    snapshot = governor.snapshot("task-1")

    assert response.provider == "openai"
    assert response.text.startswith("[simulated:openai/")
    assert snapshot["spent_usd"] > 0
    assert snapshot["remaining_usd"] < snapshot["budget_usd"]

    asyncio.run(router.aclose())
