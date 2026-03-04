"""Tests for Growth Swarm agent scaffolding."""

from __future__ import annotations

import asyncio

import pytest

from archon.config import ArchonConfig
from archon.core.growth_router import GrowthSwarmRouter
from archon.providers import ProviderRouter


def test_growth_swarm_builder_instantiates_all_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    provider_router = ProviderRouter(config=ArchonConfig(), live_mode=False)
    swarm = GrowthSwarmRouter(provider_router).build_growth_swarm()

    assert swarm.prospector.name == "ProspectorAgent"
    assert swarm.icp.name == "ICPAgent"
    assert swarm.outreach.name == "OutreachAgent"
    assert swarm.nurture.name == "NurtureAgent"
    assert swarm.revenue_intel.name == "RevenueIntelAgent"
    assert swarm.partner.name == "PartnerAgent"
    assert swarm.churn_defense.name == "ChurnDefenseAgent"

    asyncio.run(provider_router.aclose())


def test_growth_agents_produce_action_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    provider_router = ProviderRouter(config=ArchonConfig(), live_mode=False)
    swarm = GrowthSwarmRouter(provider_router).build_growth_swarm()

    async def _run_all():
        return [
            await swarm.prospector.run("Grow qualified pipeline", {"market": "India"}, "g-1"),
            await swarm.icp.run("Refine targeting", {"wins": ["clinic-a"]}, "g-2"),
            await swarm.outreach.run("Increase demos", {"sector": "pharmacy"}, "g-3"),
            await swarm.nurture.run("Recover warm leads", {"funnel_events": {"stalled": 12}}, "g-4"),
            await swarm.revenue_intel.run("Find bottlenecks", {"funnel": {"mql_to_sql": 0.34}}, "g-5"),
            await swarm.partner.run("Expand channel network", {"region": "India"}, "g-6"),
            await swarm.churn_defense.run("Reduce churn", {"risk_accounts": ["acct-1"]}, "g-7"),
        ]

    results = asyncio.run(_run_all())
    for result in results:
        assert isinstance(result.output, str)
        assert result.metadata["provider"] == "openrouter"
        assert isinstance(result.metadata["actions"], list)
        assert result.metadata["actions"]

    asyncio.run(provider_router.aclose())

