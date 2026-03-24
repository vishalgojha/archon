"""Typed billing models and plan catalog."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


def _now() -> float:
    return time.time()


def _identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True, slots=True)
class BillingPlan:
    """One monthly billing plan definition."""

    plan_id: str
    name: str
    base_monthly_usd: float
    included_model_spend_usd: float
    included_outbound_actions: int
    outbound_overage_usd: float


PLAN_CATALOG: dict[str, BillingPlan] = {
    "free": BillingPlan("free", "Free", 0.0, 5.0, 50, 0.05),
    "pro": BillingPlan("pro", "Pro", 49.0, 25.0, 500, 0.02),
    "enterprise": BillingPlan("enterprise", "Enterprise", 999.0, 500.0, 50000, 0.005),
}


def get_plan(plan_id: str) -> BillingPlan:
    """Return one plan by id.

    Example:
        >>> get_plan("pro").base_monthly_usd
        49.0
    """

    normalized = str(plan_id or "").strip().lower()
    if normalized not in PLAN_CATALOG:
        raise KeyError(f"Unknown billing plan '{plan_id}'.")
    return PLAN_CATALOG[normalized]


def list_plans() -> list[BillingPlan]:
    """Return the plan catalog in deterministic order.

    Example:
        >>> [plan.plan_id for plan in list_plans()]
        ['free', 'pro', 'enterprise']
    """

    return [PLAN_CATALOG[key] for key in ("free", "pro", "enterprise")]


@dataclass(slots=True)
class BillingCustomer:
    """Tenant billing identity."""

    tenant_id: str
    customer_id: str = field(default_factory=lambda: _identifier("cust"))
    email: str = ""
    name: str = ""
    status: str = "active"
    external_customer_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)


@dataclass(slots=True)
class BillingSubscription:
    """Tenant subscription state for one billing cycle."""

    tenant_id: str
    plan_id: str
    subscription_id: str = field(default_factory=lambda: _identifier("sub"))
    status: str = "active"
    external_subscription_id: str | None = None
    period_start: float = field(default_factory=_now)
    period_end: float = field(default_factory=_now)
    cancel_at_period_end: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class SubscriptionChange:
    """Plan change marker used for prorated invoice calculations."""

    tenant_id: str
    plan_id: str
    effective_at: float
    change_id: str = field(default_factory=lambda: _identifier("chg"))
    created_at: float = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """Metered billing usage row."""

    tenant_id: str
    meter_type: str
    quantity: float
    amount_usd: float
    usage_id: str = field(default_factory=lambda: _identifier("usage"))
    provider: str = ""
    model: str = ""
    action_type: str = ""
    task_id: str = ""
    timestamp: float = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    """One invoice line item."""

    description: str
    meter_type: str
    quantity: float
    unit_amount_usd: float
    amount_usd: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BillingInvoice:
    """Tenant invoice document."""

    tenant_id: str
    plan_id: str
    subscription_id: str
    period_start: float
    period_end: float
    lines: list[InvoiceLine]
    invoice_id: str = field(default_factory=lambda: _identifier("inv"))
    subtotal_usd: float = 0.0
    tax_usd: float = 0.0
    total_usd: float = 0.0
    currency: str = "usd"
    status: str = "draft"
    external_invoice_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    """Verified webhook envelope."""

    event_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: float
