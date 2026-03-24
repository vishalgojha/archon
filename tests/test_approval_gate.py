"""Tests for ApprovalGate async approval workflow."""

from __future__ import annotations

import pytest

from archon.core.approval_gate import (
    ApprovalDeniedError,
    ApprovalGate,
    ApprovalRequiredError,
    ApprovalTimeoutError,
)


@pytest.mark.asyncio
async def test_guard_auto_approves_non_sensitive_action() -> None:
    gate = ApprovalGate()
    decision = await gate.guard(action_type="read_only_analysis", payload={}, event_sink=None)

    assert decision.approved is True
    assert decision.action_type == "read_only_analysis"


@pytest.mark.asyncio
async def test_guard_emits_event_and_accepts_approval() -> None:
    gate = ApprovalGate()
    events: list[dict[str, object]] = []

    async def sink(event: dict[str, object]) -> None:
        events.append(event)
        if event["type"] == "approval_required":
            gate.approve(str(event["request_id"]), approver="human-reviewer", notes="Approved")

    decision = await gate.guard(
        action_type="outbound_email",
        payload={"to": "lead@example.com"},
        event_sink=sink,
        timeout_seconds=1.0,
    )

    assert decision.approved is True
    assert decision.action_type == "outbound_email"
    assert decision.approver == "human-reviewer"
    assert events and events[0]["type"] == "approval_required"


@pytest.mark.asyncio
async def test_guard_raises_on_denial() -> None:
    gate = ApprovalGate()

    async def sink(event: dict[str, object]) -> None:
        if event["type"] == "approval_required":
            gate.deny(str(event["request_id"]), approver="human-reviewer", notes="Denied")

    with pytest.raises(ApprovalDeniedError):
        await gate.guard(
            action_type="outbound_sms",
            payload={"to": "+15551234567"},
            event_sink=sink,
            timeout_seconds=1.0,
        )


@pytest.mark.asyncio
async def test_guard_requires_event_sink_for_sensitive_action() -> None:
    gate = ApprovalGate()

    with pytest.raises(ApprovalRequiredError):
        await gate.guard(
            action_type="outbound_whatsapp",
            payload={"to": "+15551234567"},
            event_sink=None,
        )


@pytest.mark.asyncio
async def test_guard_times_out_when_no_decision() -> None:
    gate = ApprovalGate(default_timeout_seconds=0.01)

    async def sink(event: dict[str, object]) -> None:
        return None

    with pytest.raises(ApprovalTimeoutError):
        await gate.guard(
            action_type="outbound_voice",
            payload={"to": "+15551234567"},
            event_sink=sink,
            timeout_seconds=0.01,
        )
