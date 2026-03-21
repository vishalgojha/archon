"""Tests for the Textual-based agentic TUI state."""

from __future__ import annotations

import pytest

from archon.config import ArchonConfig
from archon.interfaces.cli import tui


def test_tui_state_tracks_task_events() -> None:
    state = tui.TuiState(mode="auto", context={})

    state.apply_event(
        {
            "type": "task_started",
            "task_id": "task-123",
            "goal": "Explain CAP theorem",
            "mode": "debate",
        }
    )
    state.apply_event(
        {
            "type": "debate_round_completed",
            "task_id": "task-123",
            "round": 1,
            "total_rounds": 6,
            "agent": "ResearcherAgent",
            "confidence": 72,
        }
    )
    state.apply_event(
        {
            "type": "cost_update",
            "task_id": "task-123",
            "spent": 0.42,
            "budget": 1.0,
        }
    )
    state.apply_event(
        {
            "type": "task_completed",
            "task_id": "task-123",
            "mode": "debate",
            "confidence": 88,
            "budget": {"spent_usd": 0.42, "limit_usd": 1.0},
        }
    )

    assert "task-123" not in state.active_tasks
    assert state.history[0].task_id == "task-123"
    assert state.history[0].confidence == 88
    assert state.history[0].spent_usd == pytest.approx(0.42)


def test_tui_state_tracks_approval_events() -> None:
    state = tui.TuiState(mode="debate", context={})

    state.apply_event(
        {
            "type": "approval_required",
            "request_id": "approval-1",
            "action_type": "ui_pack_build",
            "risk_level": "HIGH",
            "context": {"version": "v1"},
        }
    )
    assert "approval-1" in state.pending_approvals

    state.apply_event(
        {
            "type": "approval_resolved",
            "request_id": "approval-1",
            "approved": True,
        }
    )
    assert "approval-1" not in state.pending_approvals


@pytest.mark.asyncio
async def test_run_agentic_tui_launches_textual(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, object] = {}

    class _FakeApp:
        def __init__(
            self,
            *,
            config: ArchonConfig,
            initial_mode: str,
            initial_context: dict[str, object],
            config_path: str,
        ) -> None:
            created["config"] = config
            created["initial_mode"] = initial_mode
            created["initial_context"] = initial_context
            created["config_path"] = config_path

        async def run_async(self) -> None:
            created["ran"] = True

    monkeypatch.setattr(tui, "ArchonTuiApp", _FakeApp)

    await tui.run_agentic_tui(
        config=ArchonConfig(),
        initial_mode="debate",
        initial_context={"sector": "pharma"},
        config_path="config.archon.yaml",
    )

    assert created.get("ran") is True
    assert created["initial_mode"] == "debate"
    assert created["initial_context"] == {"sector": "pharma"}
