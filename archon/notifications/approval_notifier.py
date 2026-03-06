"""Bridge ApprovalGate events to mobile push notifications."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from archon.core.approval_gate import ApprovalGate
from archon.notifications.device_registry import DeviceRegistry
from archon.notifications.push import Notification, PushNotifier

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


class ApprovalNotifier:
    """Sends push notifications when approval events are emitted."""

    def __init__(
        self,
        registry: DeviceRegistry,
        notifier: PushNotifier,
        *,
        deep_link_prefix: str = "archon://approvals",
    ) -> None:
        self.registry = registry
        self.notifier = notifier
        self.deep_link_prefix = deep_link_prefix.rstrip("/")

    async def handle_event(
        self,
        *,
        event: dict[str, Any],
        action_name: str,
        action_id: str,
        tenant_id: str,
        timeout_seconds: float,
        gate: ApprovalGate,
    ) -> None:
        if str(event.get("type")) != "approval_required":
            return
        if not str(tenant_id or "").strip():
            return

        base = Notification(
            title="Approval required",
            body=f"ARCHON needs your approval: {action_name}",
            data={
                "action_id": action_id,
                "deeplink": f"{self.deep_link_prefix}/{action_id}",
            },
            badge=1,
            sound="default",
        )
        self.notifier.send_to_tenant(tenant_id, base)

        if timeout_seconds <= 0:
            return
        asyncio.create_task(
            self._send_timeout_reminder(
                gate=gate,
                tenant_id=tenant_id,
                action_name=action_name,
                action_id=action_id,
                timeout_seconds=timeout_seconds,
            )
        )

    async def _send_timeout_reminder(
        self,
        *,
        gate: ApprovalGate,
        tenant_id: str,
        action_name: str,
        action_id: str,
        timeout_seconds: float,
    ) -> None:
        await asyncio.sleep(max(0.0, timeout_seconds * 0.5))
        if any(str(item.get("action_id")) == action_id for item in gate.pending_actions):
            reminder = Notification(
                title="Approval reminder",
                body=f"ARCHON needs your approval: {action_name}",
                data={
                    "action_id": action_id,
                    "deeplink": f"{self.deep_link_prefix}/{action_id}",
                    "reminder": "true",
                },
                badge=1,
                sound="default",
            )
            self.notifier.send_to_tenant(tenant_id, reminder)


def wrap_gate(gate: ApprovalGate, registry: DeviceRegistry, notifier: PushNotifier) -> ApprovalGate:
    """Wrap gate.check so emitted approval events also trigger push notifications."""

    if getattr(gate, "_approval_notifier_wrapped", False):
        return gate

    bridge = ApprovalNotifier(registry=registry, notifier=notifier)
    original_check = gate.check

    async def wrapped_check(action: str, context: dict[str, Any], action_id: str) -> str:
        raw_context = dict(context or {})
        timeout_seconds = float(raw_context.get("timeout_seconds", gate.default_timeout_seconds))
        tenant_id = str(raw_context.get("tenant_id", "")).strip()

        requested_sink = raw_context.get("event_sink")
        if callable(requested_sink):
            base_sink = requested_sink
        else:
            base_sink = getattr(gate, "_event_sink", None)

        async def combined_sink(event: dict[str, Any]) -> None:
            if callable(base_sink):
                await base_sink(event)
            await bridge.handle_event(
                event=event,
                action_name=action,
                action_id=action_id,
                tenant_id=tenant_id,
                timeout_seconds=timeout_seconds,
                gate=gate,
            )

        raw_context["event_sink"] = combined_sink
        return await original_check(action=action, context=raw_context, action_id=action_id)

    setattr(gate, "check", wrapped_check)
    setattr(gate, "_approval_notifier_wrapped", True)
    return gate
