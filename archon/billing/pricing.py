"""Pricing and proration helpers for ARCHON billing."""

from __future__ import annotations

from dataclasses import dataclass

from archon.billing.models import InvoiceLine, SubscriptionChange, UsageRecord, get_plan


@dataclass(frozen=True, slots=True)
class PlanSegment:
    """Time-bounded plan slice used for proration."""

    plan_id: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        """Return segment duration in seconds."""

        return max(0.0, self.end - self.start)


def subscription_segments(
    changes: list[SubscriptionChange],
    *,
    active_plan_id: str,
    period_start: float,
    period_end: float,
) -> list[PlanSegment]:
    """Build prorated plan segments for one invoice period.

    Example:
        >>> rows = [SubscriptionChange("t", "growth", 10.0), SubscriptionChange("t", "business", 20.0)]
        >>> [segment.plan_id for segment in subscription_segments(rows, active_plan_id="business", period_start=10.0, period_end=30.0)]
        ['growth', 'business']
    """

    if period_end <= period_start:
        raise ValueError("period_end must be greater than period_start.")

    ordered = sorted(
        [row for row in changes if row.effective_at < period_end],
        key=lambda item: (item.effective_at, item.created_at, item.change_id),
    )
    current_plan_id = active_plan_id
    for row in ordered:
        if row.effective_at <= period_start:
            current_plan_id = row.plan_id

    segments: list[PlanSegment] = []
    cursor = period_start
    for row in ordered:
        if row.effective_at <= period_start:
            continue
        if cursor < row.effective_at:
            segments.append(PlanSegment(plan_id=current_plan_id, start=cursor, end=row.effective_at))
        current_plan_id = row.plan_id
        cursor = max(cursor, row.effective_at)
    if cursor < period_end:
        segments.append(PlanSegment(plan_id=current_plan_id, start=cursor, end=period_end))
    return segments or [PlanSegment(plan_id=current_plan_id, start=period_start, end=period_end)]


def invoice_lines_for_usage(
    segments: list[PlanSegment],
    usage: list[UsageRecord],
    *,
    period_start: float,
    period_end: float,
) -> list[InvoiceLine]:
    """Build base-fee and overage invoice lines for one billing period.

    Example:
        >>> segments = [PlanSegment("growth", 0.0, 30.0)]
        >>> usage = [UsageRecord("t", "model_spend", 1.0, 40.0, provider="openai", model="gpt-4o")]
        >>> any(line.meter_type == "model_spend" for line in invoice_lines_for_usage(segments, usage, period_start=0.0, period_end=30.0))
        True
    """

    duration = max(1.0, period_end - period_start)
    lines: list[InvoiceLine] = []
    included_model_spend = 0.0
    included_outbound_actions = 0.0
    action_rate_weight = 0.0

    for segment in segments:
        plan = get_plan(segment.plan_id)
        fraction = max(0.0, segment.duration / duration)
        included_model_spend += plan.included_model_spend_usd * fraction
        included_outbound_actions += float(plan.included_outbound_actions) * fraction
        action_rate_weight += plan.outbound_overage_usd * fraction
        amount = round(plan.base_monthly_usd * fraction, 2)
        if amount <= 0:
            continue
        lines.append(
            InvoiceLine(
                description=f"{plan.name} base fee ({round(fraction * 100, 2)}% prorated)",
                meter_type="plan_base",
                quantity=round(fraction, 6),
                unit_amount_usd=round(plan.base_monthly_usd, 2),
                amount_usd=amount,
                metadata={"plan_id": plan.plan_id},
            )
        )

    spend_by_pair: dict[tuple[str, str], float] = {}
    action_counts: dict[str, float] = {}
    total_model_spend = 0.0
    total_actions = 0.0
    for row in usage:
        if row.meter_type == "model_spend":
            key = (row.provider or "unknown", row.model or "unknown")
            spend_by_pair[key] = round(spend_by_pair.get(key, 0.0) + float(row.amount_usd), 6)
            total_model_spend = round(total_model_spend + float(row.amount_usd), 6)
        elif row.meter_type == "outbound_action":
            key = row.action_type or "outbound_action"
            action_counts[key] = round(action_counts.get(key, 0.0) + float(row.quantity), 6)
            total_actions = round(total_actions + float(row.quantity), 6)

    model_overage = round(max(0.0, total_model_spend - included_model_spend), 2)
    if model_overage > 0 and total_model_spend > 0:
        for (provider, model), spend in sorted(spend_by_pair.items()):
            allocation = round(model_overage * (spend / total_model_spend), 2)
            if allocation <= 0:
                continue
            lines.append(
                InvoiceLine(
                    description=f"Model spend overage: {provider}/{model}",
                    meter_type="model_spend",
                    quantity=round(spend, 6),
                    unit_amount_usd=1.0,
                    amount_usd=allocation,
                    metadata={"provider": provider, "model": model},
                )
            )

    outbound_overage_qty = max(0.0, total_actions - included_outbound_actions)
    action_rate = round(action_rate_weight, 6)
    if outbound_overage_qty > 0 and total_actions > 0 and action_rate > 0:
        for action_type, count in sorted(action_counts.items()):
            allocated_qty = round(outbound_overage_qty * (count / total_actions), 6)
            amount = round(allocated_qty * action_rate, 2)
            if amount <= 0:
                continue
            lines.append(
                InvoiceLine(
                    description=f"Outbound action overage: {action_type}",
                    meter_type="outbound_action",
                    quantity=allocated_qty,
                    unit_amount_usd=action_rate,
                    amount_usd=amount,
                    metadata={"action_type": action_type},
                )
            )
    return lines
