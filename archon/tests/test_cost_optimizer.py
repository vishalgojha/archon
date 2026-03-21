"""Tests for the adaptive cost optimizer agent."""

from __future__ import annotations

import asyncio

from archon.agents.optimization import CostOptimizerAgent
from archon.config import ArchonConfig
from archon.providers import ProviderRouter


def test_cost_optimizer_recommends_lower_cost_profile_when_quality_holds() -> None:
    router = ProviderRouter(config=ArchonConfig())
    optimizer = CostOptimizerAgent(router, min_samples=1, pressure_threshold=0.8)

    optimizer.observe_selection(
        "task-openai",
        role="coding",
        provider="openai",
        model="gpt-4o",
        cost_usd=0.24,
    )
    optimizer.record_task_feedback("task-openai", quality_score=0.93)

    optimizer.observe_selection(
        "task-groq",
        role="coding",
        provider="groq",
        model="mixtral-8x7b-32768",
        cost_usd=0.05,
    )
    optimizer.record_task_feedback("task-groq", quality_score=0.9)

    recommendation = optimizer.recommend(
        role="coding",
        current_provider="openai",
        current_model="gpt-4o",
        spend_snapshot={"budget_usd": 1.0, "spent_usd": 0.91},
    )

    assert recommendation is not None
    assert recommendation.to_provider == "groq"
    assert recommendation.estimated_savings_ratio > 0.0
    asyncio.run(router.aclose())


def test_cost_optimizer_skips_when_pressure_is_low_or_quality_drops() -> None:
    router = ProviderRouter(config=ArchonConfig())
    optimizer = CostOptimizerAgent(router, min_samples=1, pressure_threshold=0.8)

    optimizer.observe_selection(
        "task-openai",
        role="primary",
        provider="openai",
        model="o3",
        cost_usd=0.30,
    )
    optimizer.record_task_feedback("task-openai", quality_score=0.95)

    optimizer.observe_selection(
        "task-groq",
        role="primary",
        provider="groq",
        model="llama-3.3-70b-versatile",
        cost_usd=0.05,
    )
    optimizer.record_task_feedback("task-groq", quality_score=0.6)

    assert (
        optimizer.recommend(
            role="primary",
            current_provider="openai",
            current_model="o3",
            spend_snapshot={"budget_usd": 1.0, "spent_usd": 0.4},
        )
        is None
    )
    assert (
        optimizer.recommend(
            role="primary",
            current_provider="openai",
            current_model="o3",
            spend_snapshot={"budget_usd": 1.0, "spent_usd": 0.92},
        )
        is None
    )
    asyncio.run(router.aclose())
