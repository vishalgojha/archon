"""Tests for debate orchestration mode."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import httpx
import pytest

from archon.config import ArchonConfig
from archon.core.memory_store import MemoryStore
from archon.core.orchestrator import Orchestrator


def test_orchestrator_supports_debate_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    orchestrator = Orchestrator(config=ArchonConfig())
    asyncio.run(orchestrator.provider_router._http.aclose())
    orchestrator.provider_router._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 5},
                },
            )
        )
    )
    db_path = Path(f"orchestrator-memory-{uuid.uuid4().hex}.sqlite3")
    orchestrator.memory_store = MemoryStore(db_path=db_path)

    async def _run():
        try:
            debate = await orchestrator.execute(goal="Design a migration strategy", mode="debate")
            recent = await orchestrator.memory_store.list_recent(limit=5)
            return debate, recent
        finally:
            await orchestrator.aclose()

    debate_result, memory_rows = asyncio.run(_run())

    assert debate_result.mode == "debate"
    assert debate_result.debate is not None
    assert debate_result.confidence >= 0

    modes = {row["context"]["mode"] for row in memory_rows}
    assert "debate" in modes

    if db_path.exists():
        db_path.unlink()
