"""Human approval gate and policy registry for sensitive actions."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass
from functools import wraps
from threading import Lock
from typing import Any, Awaitable, Callable, Literal, ParamSpec, TypeVar

EventSink = Callable[[dict[str, Any]], Awaitable[None]]
RiskLevel = Literal["HIGH", "MEDIUM"]

HIGH_RISK_ACTIONS: frozenset[str] = frozenset(
    {
        "file_write",
        "file_delete",
        "external_api_call",
        "gui_form_submit",
        "financial_transaction",
        "send_message",
        "shell_exec",
        "email_send",
        "outbound_email",
        "outbound_sms",
        "outbound_whatsapp",
        "outbound_voice",
        "db_delete",
        "skill_propose",
        "skill_promote",
        "ui_pack_publish",
        "ui_pack_activate",
        "ui_pack_build",
    }
)
MEDIUM_RISK_ACTIONS: frozenset[str] = frozenset({"db_write", "webhook_trigger"})
REQUIRES_APPROVAL: dict[str, RiskLevel] = {
    **{name: "HIGH" for name in HIGH_RISK_ACTIONS},
    **{name: "MEDIUM" for name in MEDIUM_RISK_ACTIONS},
}

P = ParamSpec("P")
R = TypeVar("R")


class ApprovalDeniedError(RuntimeError):
    """Denied action error. Example: `ApprovalDeniedError('id','a','reason')`."""

    def __init__(self, action_id: str, action: str, reason: str) -> None:
        self.action_id = action_id
        self.action = action
        self.reason = reason
        super().__init__(f"Action '{action}' denied ({action_id}): {reason}")


class ApprovalTimeoutError(ApprovalDeniedError):
    """Timeout error. Example: `ApprovalTimeoutError('id','a').reason == 'timeout'`."""

    def __init__(self, action_id: str, action: str) -> None:
        super().__init__(action_id=action_id, action=action, reason="timeout")


class ApprovalRequiredError(RuntimeError):
    """No sink for gated action. Example: `raise ApprovalRequiredError('missing sink')`."""


@dataclass(slots=True)
class ApprovalDecision:
    """Resolved decision. Example: `ApprovalDecision('id','a',True).approved`."""

    request_id: str
    action_type: str
    approved: bool
    approver: str | None = None
    notes: str | None = None

    def to_event_payload(self) -> dict[str, Any]:
        """Serialize decision. Example: `ApprovalDecision('i','a',True).to_event_payload()`."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class ApprovalAuditEntry:
    """Immutable audit row. Example: `ApprovalAuditEntry(...).approved`."""

    action_id: str
    action: str
    risk_level: RiskLevel | None
    approved: bool
    reason: str
    approver: str | None
    created_at: float


@dataclass(slots=True)
class _PendingAction:
    action_id: str
    action: str
    risk_level: RiskLevel
    context: dict[str, Any]
    created_at: float
    event: asyncio.Event
    decision: ApprovalDecision | None = None


def requires_approval(action_name: str, *, supervised_mode: bool = False) -> bool:
    """Policy predicate. Example: `requires_approval('file_write') -> True`."""

    risk = REQUIRES_APPROVAL.get(action_name)
    if risk == "HIGH":
        return True
    if risk == "MEDIUM":
        return supervised_mode
    return False


class ApprovalGate:
    """Async approval coordinator. Example: `ApprovalGate().pending_actions`."""

    def __init__(
        self,
        requires_approval_registry: dict[str, RiskLevel] | None = None,
        *,
        supervised_mode: bool = False,
        default_timeout_seconds: float = 120.0,
        auto_approve_in_test: bool = False,
        event_sink: EventSink | None = None,
    ) -> None:
        """Init gate. Example: `ApprovalGate(default_timeout_seconds=30.0)`."""

        self.requires_approval_registry = requires_approval_registry or dict(REQUIRES_APPROVAL)
        self.supervised_mode = supervised_mode
        self.default_timeout_seconds = default_timeout_seconds
        self.auto_approve_in_test = auto_approve_in_test
        self._event_sink = event_sink
        self._pending: dict[str, _PendingAction] = {}
        self._decision_history: list[ApprovalAuditEntry] = []
        self._resolved: dict[str, ApprovalDecision] = {}
        self._lock = Lock()

    async def check(self, action: str, context: dict[str, Any], action_id: str) -> str:
        """Gate action. Example: `await gate.check('file_write', {}, 'a-1')`."""

        if not self.requires_approval(action):
            self._finalize(
                ApprovalDecision(action_id, action, True, approver="system", notes="not_gated"),
                risk_level=self.requires_approval_registry.get(action),
                reason="not_gated",
            )
            return action_id

        if self.auto_approve_in_test:
            self._finalize(
                ApprovalDecision(action_id, action, True, approver="system", notes="auto_approve"),
                risk_level=self.requires_approval_registry[action],
                reason="auto_approve_in_test",
            )
            return action_id

        event_sink = self._event_sink
        if callable(context.get("event_sink")):
            event_sink = context["event_sink"]
        if event_sink is None:
            raise ApprovalRequiredError(f"Action '{action}' requires approval but no event sink.")

        timeout_seconds = float(context.get("timeout_seconds", self.default_timeout_seconds))
        pending = _PendingAction(
            action_id=action_id,
            action=action,
            risk_level=self.requires_approval_registry[action],
            context={
                k: v for k, v in context.items() if k not in {"event_sink", "timeout_seconds"}
            },
            created_at=time.time(),
            event=asyncio.Event(),
        )
        with self._lock:
            self._pending[action_id] = pending

        await event_sink(
            {
                "type": "approval_required",
                "request_id": action_id,
                "action_id": action_id,
                "action_type": action,
                "action": action,
                "risk_level": pending.risk_level,
                "context": pending.context,
            }
        )

        try:
            await asyncio.wait_for(pending.event.wait(), timeout=timeout_seconds)
        except TimeoutError as exc:
            with self._lock:
                self._pending.pop(action_id, None)
            self._finalize(
                ApprovalDecision(action_id, action, False, approver="system", notes="timeout"),
                risk_level=pending.risk_level,
                reason="timeout",
            )
            raise ApprovalTimeoutError(action_id=action_id, action=action) from exc

        with self._lock:
            current = self._pending.pop(action_id, None)
        decision = current.decision if current else None
        if decision is None:
            self._finalize(
                ApprovalDecision(action_id, action, False, notes="missing_decision"),
                risk_level=pending.risk_level,
                reason="missing_decision",
            )
            raise ApprovalDeniedError(action_id=action_id, action=action, reason="missing_decision")
        if not decision.approved:
            raise ApprovalDeniedError(
                action_id=action_id, action=action, reason=decision.notes or "denied"
            )
        return action_id

    async def guard(
        self,
        *,
        action_type: str,
        payload: dict[str, Any],
        event_sink: EventSink | None = None,
        timeout_seconds: float | None = None,
    ) -> ApprovalDecision:
        """Legacy API. Example: `await gate.guard(action_type='a', payload={})`."""

        action_id = f"approval-{uuid.uuid4().hex[:12]}"
        context = dict(payload)
        if event_sink:
            context["event_sink"] = event_sink
        if timeout_seconds is not None:
            context["timeout_seconds"] = timeout_seconds
        await self.check(action=action_type, context=context, action_id=action_id)
        return self._resolved[action_id]

    def requires_approval(self, action_name: str, *, supervised_mode: bool | None = None) -> bool:
        """Instance predicate. Example: `ApprovalGate().requires_approval('file_write')`."""

        mode = self.supervised_mode if supervised_mode is None else supervised_mode
        risk = self.requires_approval_registry.get(action_name)
        if risk == "HIGH":
            return True
        if risk == "MEDIUM":
            return mode
        return False

    def approve(
        self, action_id: str, *, approver: str | None = None, notes: str | None = None
    ) -> bool:
        """Approve action. Example: `gate.approve('id')`."""

        return self._resolve(
            action_id, approved=True, approver=approver, reason=notes or "approved"
        )

    def deny(
        self,
        action_id: str,
        reason: str | None = None,
        *,
        approver: str | None = None,
        notes: str | None = None,
    ) -> bool:
        """Deny action. Example: `gate.deny('id', reason='policy')`."""

        return self._resolve(
            action_id, approved=False, approver=approver, reason=reason or notes or "denied"
        )

    @property
    def pending_actions(self) -> tuple[dict[str, Any], ...]:
        """Pending queue. Example: `ApprovalGate().pending_actions == ()`."""

        with self._lock:
            return tuple(
                {
                    "action_id": row.action_id,
                    "action": row.action,
                    "risk_level": row.risk_level,
                    "created_at": row.created_at,
                    "context": dict(row.context),
                }
                for row in sorted(self._pending.values(), key=lambda item: item.created_at)
            )

    @property
    def decision_history(self) -> tuple[ApprovalAuditEntry, ...]:
        """Immutable history. Example: `isinstance(gate.decision_history, tuple)`."""

        with self._lock:
            return tuple(self._decision_history)

    async def pending_requests(self) -> list[str]:
        """Legacy pending IDs. Example: `await gate.pending_requests()`."""

        return [item["action_id"] for item in self.pending_actions]

    def _resolve(
        self, action_id: str, *, approved: bool, approver: str | None, reason: str
    ) -> bool:
        with self._lock:
            pending = self._pending.get(action_id)
            if pending is None or pending.decision is not None:
                return False
            pending.decision = ApprovalDecision(
                action_id, pending.action, approved, approver, reason
            )
            decision = pending.decision
        self._finalize(decision, risk_level=pending.risk_level, reason=reason)
        pending.event.set()
        return True

    def _finalize(
        self, decision: ApprovalDecision, *, risk_level: RiskLevel | None, reason: str
    ) -> None:
        entry = ApprovalAuditEntry(
            action_id=decision.request_id,
            action=decision.action_type,
            risk_level=risk_level,
            approved=decision.approved,
            reason=reason,
            approver=decision.approver,
            created_at=time.time(),
        )
        with self._lock:
            self._decision_history.append(entry)
            self._resolved[decision.request_id] = decision


def requires_gate(
    action_name: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorator that gates async methods. Example: `@requires_gate('file_write')`."""

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            self_obj = args[0] if args else None
            gate = kwargs.get("approval_gate")
            if gate is None and self_obj is not None:
                gate = getattr(self_obj, "approval_gate", None) or getattr(self_obj, "gate", None)
            if not isinstance(gate, ApprovalGate):
                raise RuntimeError(
                    "requires_gate expects ApprovalGate on self.approval_gate or kwargs."
                )
            context = (
                dict(kwargs.get("context", {})) if isinstance(kwargs.get("context"), dict) else {}
            )
            if callable(kwargs.get("event_sink")):
                context["event_sink"] = kwargs["event_sink"]
            if kwargs.get("timeout_seconds") is not None:
                context["timeout_seconds"] = kwargs["timeout_seconds"]
            action_id = str(
                kwargs.get("action_id")
                or kwargs.get("request_id")
                or kwargs.get("task_id")
                or f"{action_name}-{uuid.uuid4().hex[:12]}"
            )
            await gate.check(action=action_name, context=context, action_id=action_id)
            return await func(*args, **kwargs)

        return wrapper

    return decorator
