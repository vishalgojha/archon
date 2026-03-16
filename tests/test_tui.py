"""Tests for the agentic terminal UI."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

from archon.config import ArchonConfig
from archon.core.orchestrator import OrchestrationResult
from archon.interfaces.cli import tui


def _line_reader(lines: list[str]):
    iterator: Iterator[str] = iter(lines)

    async def _read(_prompt: str) -> str:
        return next(iterator)

    return _read


class _FakeApprovalGate:
    def __init__(self) -> None:
        self.approved: list[str] = []
        self.denied: list[str] = []

    def approve(
        self, request_id: str, *, approver: str | None = None, notes: str | None = None
    ) -> bool:
        del approver, notes
        self.approved.append(request_id)
        return True

    def deny(
        self,
        request_id: str,
        reason: str | None = None,
        *,
        approver: str | None = None,
    ) -> bool:
        del reason, approver
        self.denied.append(request_id)
        return True


class _FakeOrchestrator:
    calls: list[dict[str, Any]] = []
    emitted_approval: bool = False

    def __init__(self, config: ArchonConfig, live_provider_calls: bool = False) -> None:
        del config
        self.live_provider_calls = live_provider_calls
        self.approval_gate = _FakeApprovalGate()
        self.closed = False

    async def execute(
        self,
        *,
        goal: str,
        mode: str,
        context: dict[str, Any] | None = None,
        event_sink=None,
        **_: Any,
    ) -> OrchestrationResult:
        _FakeOrchestrator.calls.append(
            {
                "goal": goal,
                "mode": mode,
                "context": dict(context or {}),
                "live_provider_calls": self.live_provider_calls,
            }
        )
        if event_sink is not None:
            await event_sink({"type": "task_started", "task_id": "task-123", "mode": mode})
            await event_sink(
                {
                    "type": "debate_round_completed",
                    "round": 1,
                    "total_rounds": 6,
                    "agent": "ResearcherAgent",
                    "confidence": 72,
                    "output_preview": "Mapped the design space.",
                }
            )
            if not _FakeOrchestrator.emitted_approval and "guarded_action" in (context or {}):
                _FakeOrchestrator.emitted_approval = True
                await event_sink(
                    {
                        "type": "approval_required",
                        "request_id": "approval-1",
                        "action_type": "ui_pack_build",
                        "risk_level": "HIGH",
                        "context": {"version": "v1"},
                    }
                )
            await event_sink(
                {
                    "type": "task_completed",
                    "mode": mode,
                    "confidence": 88,
                    "budget": {"spent_usd": 0.42},
                }
            )

        return OrchestrationResult(
            task_id="task-123",
            goal=goal,
            mode="debate",
            final_answer="Debate result ready.",
            confidence=88,
            budget={"spent_usd": 0.42},
            debate={
                "rounds": [
                    {
                        "agent": "ResearcherAgent",
                        "confidence": 72,
                        "output": "Mapped the design space.",
                    },
                    {
                        "agent": "SynthesizerAgent",
                        "confidence": 88,
                        "output": "Selected the safest path.",
                    },
                ],
                "dissent": ["Critic noted rollout risk."],
            },
        )

    async def aclose(self) -> None:
        self.closed = True


def test_run_agentic_tui_renders_debate_events_and_history(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _FakeOrchestrator.calls = []
    _FakeOrchestrator.emitted_approval = False
    monkeypatch.setattr(
        tui, "_read_session_line", _line_reader(["Explain CAP theorem", "/history", "/quit"])
    )
    monkeypatch.setattr(tui, "Orchestrator", _FakeOrchestrator)

    asyncio.run(tui.run_agentic_tui(config=ArchonConfig(), initial_mode="auto"))

    output = capsys.readouterr().out
    assert "ResearcherAgent | round 1/6" in output
    assert "Confidence: 72%" in output
    assert "Debate result ready." in output
    assert "1. [debate] Explain CAP theorem -> 88% ($0.4200)" in output
    assert _FakeOrchestrator.calls[0]["mode"] == "debate"


def test_run_agentic_tui_updates_mode_context_and_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _FakeOrchestrator.calls = []
    _FakeOrchestrator.emitted_approval = False
    monkeypatch.setattr(
        tui,
        "_read_session_line",
        _line_reader(
            [
                "/mode debate",
                '/context {"market":"India","sector":"pharmacy"}',
                "Increase qualified leads",
                "/status",
                "/quit",
            ]
        ),
    )
    monkeypatch.setattr(tui, "Orchestrator", _FakeOrchestrator)

    asyncio.run(tui.run_agentic_tui(config=ArchonConfig(), initial_mode="auto"))

    output = capsys.readouterr().out
    assert "Mode set to debate." in output
    assert "Context updated with 2 keys." in output
    assert "Mode=debate" in output
    assert _FakeOrchestrator.calls[0]["context"] == {"market": "India", "sector": "pharmacy"}


def test_run_agentic_tui_routes_approval_events_back_into_gate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured_gates: list[_FakeApprovalGate] = []

    class _ApprovalOrchestrator(_FakeOrchestrator):
        def __init__(self, config: ArchonConfig, live_provider_calls: bool = False) -> None:
            super().__init__(config=config, live_provider_calls=live_provider_calls)
            captured_gates.append(self.approval_gate)

    _FakeOrchestrator.calls = []
    _FakeOrchestrator.emitted_approval = False
    monkeypatch.setattr(
        tui,
        "_read_session_line",
        _line_reader(
            [
                '/context {"guarded_action":{"action_type":"ui_pack_build","payload":{"version":"v1"}}}',
                "Create pack",
                "/quit",
            ]
        ),
    )
    monkeypatch.setattr(
        tui, "_prompt_approval_decision", lambda event: asyncio.sleep(0, result=True)
    )
    monkeypatch.setattr(tui, "Orchestrator", _ApprovalOrchestrator)

    asyncio.run(tui.run_agentic_tui(config=ArchonConfig(), initial_mode="debate"))

    output = capsys.readouterr().out
    assert "Approval required" in output
    assert "ui_pack_build requested (HIGH)" in output
    assert "approved approval-1" in output
    assert captured_gates[0].approved == ["approval-1"]


def test_run_agentic_tui_intercepts_shell_style_inputs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _FakeOrchestrator.calls = []
    _FakeOrchestrator.emitted_approval = False
    monkeypatch.setattr(
        tui,
        "_read_session_line",
        _line_reader(["archon tui", "archon shell", "/quit"]),
    )
    monkeypatch.setattr(tui, "Orchestrator", _FakeOrchestrator)

    asyncio.run(tui.run_agentic_tui(config=ArchonConfig(), initial_mode="auto"))

    output = capsys.readouterr().out
    assert "Already in TUI" in output
    assert "Shell command detected" in output
    assert _FakeOrchestrator.calls == []
