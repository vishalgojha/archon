"""Human approval gate for sensitive agent actions."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable

EventSink = Callable[[dict[str, Any]], Awaitable[None]]

REQUIRES_APPROVAL: set[str] = {
    "outbound_email",
    "outbound_webchat",
    "outbound_sms",
    "outbound_whatsapp",
    "outbound_linkedin",
    "outbound_voice",
    "partner_payout",
    "price_override",
    "contract_commit",
}


class ApprovalDeniedError(RuntimeError):
    """Raised when an approval request is explicitly denied."""


class ApprovalTimeoutError(RuntimeError):
    """Raised when an approval request times out."""


class ApprovalRequiredError(RuntimeError):
    """Raised when approval is required but no event sink is available."""


@dataclass(slots=True)
class ApprovalDecision:
    """Resolved decision for one guarded action."""

    request_id: str
    action_type: str
    approved: bool
    approver: str | None = None
    notes: str | None = None

    def to_event_payload(self) -> dict[str, Any]:
        return asdict(self)


class ApprovalGate:
    """Coordinates approval requests and asynchronous approve/deny callbacks."""

    def __init__(
        self,
        requires_approval: set[str] | None = None,
        default_timeout_seconds: float = 300.0,
    ) -> None:
        self.requires_approval = requires_approval or set(REQUIRES_APPROVAL)
        self.default_timeout_seconds = default_timeout_seconds
        self._pending: dict[str, tuple[str, asyncio.Future[ApprovalDecision]]] = {}
        self._lock = asyncio.Lock()

    async def guard(
        self,
        *,
        action_type: str,
        payload: dict[str, Any],
        event_sink: EventSink | None = None,
        timeout_seconds: float | None = None,
    ) -> ApprovalDecision:
        """Require approval for sensitive actions; auto-approve safe actions."""

        if action_type not in self.requires_approval:
            return ApprovalDecision(
                request_id=f"auto-{uuid.uuid4().hex[:10]}",
                action_type=action_type,
                approved=True,
                approver="system",
                notes="Action not in approval-required list.",
            )

        if event_sink is None:
            raise ApprovalRequiredError(
                f"Action '{action_type}' requires approval but no event sink is available."
            )

        request_id = f"approval-{uuid.uuid4().hex[:12]}"
        decision_future: asyncio.Future[ApprovalDecision] = (
            asyncio.get_running_loop().create_future()
        )

        async with self._lock:
            self._pending[request_id] = (action_type, decision_future)

        await event_sink(
            {
                "type": "approval_required",
                "request_id": request_id,
                "action_type": action_type,
                "payload": payload,
            }
        )

        timeout = timeout_seconds or self.default_timeout_seconds
        try:
            decision = await asyncio.wait_for(decision_future, timeout=timeout)
        except TimeoutError as exc:
            async with self._lock:
                self._pending.pop(request_id, None)
            raise ApprovalTimeoutError(
                f"Approval request timed out for action '{action_type}' ({request_id})."
            ) from exc

        if not decision.approved:
            raise ApprovalDeniedError(
                f"Action '{action_type}' denied by {decision.approver or 'unknown approver'}."
            )
        return decision

    async def pending_requests(self) -> list[str]:
        """Return IDs of currently pending approvals."""

        async with self._lock:
            return sorted(self._pending.keys())

    def approve(self, request_id: str, *, approver: str, notes: str | None = None) -> bool:
        """Approve a pending request by ID."""

        decision = ApprovalDecision(
            request_id=request_id,
            action_type="unknown",
            approved=True,
            approver=approver,
            notes=notes,
        )
        return self._resolve(request_id, decision)

    def deny(self, request_id: str, *, approver: str, notes: str | None = None) -> bool:
        """Deny a pending request by ID."""

        decision = ApprovalDecision(
            request_id=request_id,
            action_type="unknown",
            approved=False,
            approver=approver,
            notes=notes,
        )
        return self._resolve(request_id, decision)

    def _resolve(self, request_id: str, decision: ApprovalDecision) -> bool:
        pending = self._pending.pop(request_id, None)
        if not pending:
            return False
        action_type, future = pending
        if future.done():
            return False
        if decision.action_type == "unknown":
            decision.action_type = action_type
        future.set_result(decision)
        return True
