"""Tests for debate vs growth orchestration modes."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from archon.config import ArchonConfig
from archon.core.memory_store import MemoryStore
from archon.core.orchestrator import Orchestrator


def test_orchestrator_supports_debate_and_growth_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    orchestrator = Orchestrator(config=ArchonConfig(), live_provider_calls=False)
    db_path = Path(f"orchestrator-memory-{uuid.uuid4().hex}.sqlite3")
    orchestrator.memory_store = MemoryStore(db_path=db_path)

    async def _run():
        try:
            debate = await orchestrator.execute(goal="Design a migration strategy", mode="debate")
            growth = await orchestrator.execute(
                goal="Increase qualified leads in Indian pharmacy SMBs",
                mode="growth",
                context={"market": "India", "sector": "pharmacy"},
            )
            recent = await orchestrator.memory_store.list_recent(limit=5)
            return debate, growth, recent
        finally:
            await orchestrator.aclose()

    debate_result, growth_result, memory_rows = asyncio.run(_run())

    assert debate_result.mode == "debate"
    assert debate_result.debate is not None
    assert debate_result.growth is None
    assert debate_result.confidence >= 0

    assert growth_result.mode == "growth"
    assert growth_result.growth is not None
    assert growth_result.debate is None
    assert len(growth_result.growth["agent_reports"]) == 7
    assert len(growth_result.growth["recommended_actions"]) >= 7

    modes = {row["context"]["mode"] for row in memory_rows}
    assert "debate" in modes
    assert "growth" in modes

    if db_path.exists():
        db_path.unlink()
