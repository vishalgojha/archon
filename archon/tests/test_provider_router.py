"""Unit tests for provider resolution and live invocation."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from archon.agents.optimization import CostOptimizerAgent
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


def test_resolve_provider_uses_configured_ollama_models() -> None:
    config = ArchonConfig.model_validate(
        {
            "byok": {
                "primary": "ollama",
                "coding": "ollama",
                "vision": "ollama",
                "fast": "ollama",
                "embedding": "ollama",
                "fallback": "ollama",
                "ollama_primary_model": "llama3.1:latest",
                "ollama_coding_model": "llama3.1:latest",
                "ollama_fast_model": "llama3.1:latest",
            }
        }
    )
    router = ProviderRouter(config=config)

    assert router.resolve_provider(role="primary").model == "llama3.1:latest"
    assert router.resolve_provider(role="coding").model == "llama3.1:latest"
    assert router.resolve_provider(role="fast").model == "llama3.1:latest"


def _mock_openai_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8},
        }
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def test_invoke_charges_cost_governor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    governor = CostGovernor(default_budget_usd=1.0)
    governor.start_task("task-1")

    config = ArchonConfig()
    router = ProviderRouter(config=config, cost_governor=governor)
    asyncio.run(router._http.aclose())
    router._http = httpx.AsyncClient(transport=_mock_openai_transport())

    response = asyncio.run(
        router.invoke(role="coding", prompt="Write a SQL query", task_id="task-1")
    )
    snapshot = governor.snapshot("task-1")

    assert response.provider == "openai"
    assert response.text == "ok"
    assert snapshot["spent_usd"] > 0
    assert snapshot["remaining_usd"] < snapshot["budget_usd"]

    asyncio.run(router.aclose())


def test_router_applies_cost_optimizer_override_under_budget_pressure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")

    governor = CostGovernor(default_budget_usd=1.0)
    config = ArchonConfig()
    router = ProviderRouter(config=config, cost_governor=governor)
    asyncio.run(router._http.aclose())
    router._http = httpx.AsyncClient(transport=_mock_openai_transport())
    optimizer = CostOptimizerAgent(router, min_samples=1, pressure_threshold=0.8)
    router.set_cost_optimizer(optimizer)

    governor.start_task("learn-openai")
    asyncio.run(router.invoke(role="coding", prompt="Write SQL", task_id="learn-openai"))
    router.record_task_feedback("learn-openai", quality_score=0.93)

    governor.start_task("learn-groq")
    asyncio.run(
        router.invoke(
            role="coding",
            prompt="Write SQL",
            task_id="learn-groq",
            provider_override="groq",
        )
    )
    router.record_task_feedback("learn-groq", quality_score=0.90)

    governor.start_task("pressure-task")
    governor.add_cost("pressure-task", 0.9)
    response = asyncio.run(
        router.invoke(role="coding", prompt="Build index", task_id="pressure-task")
    )
    snapshot = governor.snapshot("pressure-task")

    assert response.provider == "groq"
    assert snapshot["optimizations"]
    assert snapshot["optimizations"][0]["to_provider"] == "groq"

    asyncio.run(router.aclose())
