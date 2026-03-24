"""Tests for risk-aware approval gate behavior and decorator integration."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from archon.core.approval_gate import (
    HIGH_RISK_ACTIONS,
    MEDIUM_RISK_ACTIONS,
    REQUIRES_APPROVAL,
    ApprovalDeniedError,
    ApprovalGate,
    ApprovalTimeoutError,
    requires_approval,
    requires_gate,
)


def test_registry_completeness() -> None:
    required_high = {
        "file_write",
        "file_delete",
        "external_api_call",
        "gui_form_submit",
        "financial_transaction",
        "send_message",
        "shell_exec",
        "email_send",
        "db_delete",
    }
    required_medium = {"db_write", "webhook_trigger"}

    assert required_high.issubset(HIGH_RISK_ACTIONS)
    assert required_medium.issubset(MEDIUM_RISK_ACTIONS)
    for action in required_high:
        assert REQUIRES_APPROVAL[action] == "HIGH"
    for action in required_medium:
        assert REQUIRES_APPROVAL[action] == "MEDIUM"


def test_requires_approval_predicate() -> None:
    assert requires_approval("file_write", supervised_mode=False) is True
    assert requires_approval("db_write", supervised_mode=False) is False
    assert requires_approval("db_write", supervised_mode=True) is True
    assert requires_approval("unknown_action", supervised_mode=True) is False

    gate_off = ApprovalGate(supervised_mode=False)
    gate_on = ApprovalGate(supervised_mode=True)
    assert gate_off.requires_approval("webhook_trigger") is False
    assert gate_on.requires_approval("webhook_trigger") is True


@pytest.mark.asyncio
async def test_approve_flow_emits_event_and_records_history() -> None:
    gate = ApprovalGate()
    events: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        events.append(event)
        assert any(row["action_id"] == event["action_id"] for row in gate.pending_actions)
        gate.approve(str(event["action_id"]), approver="human-1", notes="ok")

    action_id = "a-approve-1"
    returned = await gate.check(
        action="file_write",
        context={"event_sink": sink, "path": "tmp.txt"},
        action_id=action_id,
    )

    assert returned == action_id
    assert len(events) == 1
    assert events[0]["type"] == "approval_required"
    assert gate.pending_actions == ()
    assert gate.decision_history[-1].action_id == action_id
    assert gate.decision_history[-1].approved is True


@pytest.mark.asyncio
async def test_deny_flow_raises_with_reason() -> None:
    gate = ApprovalGate()

    async def sink(event: dict[str, Any]) -> None:
        gate.deny(str(event["action_id"]), reason="policy_blocked", approver="human-2")

    with pytest.raises(ApprovalDeniedError) as exc:
        await gate.check("shell_exec", {"event_sink": sink}, "a-deny-1")

    assert exc.value.reason == "policy_blocked"
    assert gate.decision_history[-1].approved is False
    assert gate.decision_history[-1].reason == "policy_blocked"


@pytest.mark.asyncio
async def test_timeout_raises_denied_with_timeout_reason() -> None:
    gate = ApprovalGate(default_timeout_seconds=0.01)

    async def sink(event: dict[str, Any]) -> None:
        return None

    with pytest.raises(ApprovalDeniedError) as exc:
        await gate.check("email_send", {"event_sink": sink}, "a-timeout-1")

    assert isinstance(exc.value, ApprovalTimeoutError)
    assert exc.value.reason == "timeout"
    assert gate.decision_history[-1].reason == "timeout"


@pytest.mark.asyncio
async def test_auto_approve_mode_skips_events_and_passes_immediately() -> None:
    gate = ApprovalGate(auto_approve_in_test=True)
    events: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        events.append(event)

    action_id = await gate.check("financial_transaction", {"event_sink": sink}, "a-auto-1")
    assert action_id == "a-auto-1"
    assert events == []
    assert gate.decision_history[-1].approved is True
    assert gate.decision_history[-1].reason == "auto_approve_in_test"


@pytest.mark.asyncio
async def test_pending_queue_visible_then_cleared_after_decision() -> None:
    gate = ApprovalGate(default_timeout_seconds=1.0)
    touched = asyncio.Event()

    async def sink(event: dict[str, Any]) -> None:
        touched.set()

    task = asyncio.create_task(gate.check("file_delete", {"event_sink": sink}, "a-pending-1"))
    await touched.wait()
    assert len(gate.pending_actions) == 1
    assert gate.pending_actions[0]["action_id"] == "a-pending-1"

    gate.approve("a-pending-1", approver="human-3")
    assert await task == "a-pending-1"
    assert gate.pending_actions == ()


@pytest.mark.asyncio
async def test_requires_gate_decorator_blocks_on_timeout() -> None:
    gate = ApprovalGate(default_timeout_seconds=0.01)

    class Demo:
        def __init__(self) -> None:
            self.approval_gate = gate

        @requires_gate("shell_exec")
        async def run(self, *, context: dict[str, Any], event_sink) -> str:
            return "ok"

    demo = Demo()

    async def sink(event: dict[str, Any]) -> None:
        return None

    with pytest.raises(ApprovalDeniedError) as exc:
        await demo.run(context={"target": "rm -rf"}, event_sink=sink)

    assert exc.value.reason == "timeout"
