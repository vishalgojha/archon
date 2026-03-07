"""Tenant invoice generation from metered usage independent of Stripe invoices."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from archon.billing.metering import SUPPORTED_METRICS, UsageMeter
from archon.compliance.retention import RetentionRule

INVOICE_RETENTION_RULE = RetentionRule(
    entity_type="billing_invoice",
    retention_days=2555,
    action="archive",
)

METRIC_PRICES: dict[str, dict[str, float]] = {
    "tokens_input": {"free": 0.0, "pro": 0.0000030, "enterprise": 0.0000025},
    "tokens_output": {"free": 0.0, "pro": 0.0000060, "enterprise": 0.0000050},
    "agent_runs": {"free": 0.0, "pro": 0.02, "enterprise": 0.015},
    "emails_sent": {"free": 0.0, "pro": 0.005, "enterprise": 0.004},
    "whatsapp_sent": {"free": 0.0, "pro": 0.01, "enterprise": 0.008},
    "vision_actions": {"free": 0.0, "pro": 0.03, "enterprise": 0.025},
    "memory_reads": {"free": 0.0, "pro": 0.0005, "enterprise": 0.0004},
    "memory_writes": {"free": 0.0, "pro": 0.001, "enterprise": 0.0008},
    "federation_tasks": {"free": 0.0, "pro": 0.04, "enterprise": 0.03},
}


def _invoice_id() -> str:
    return f"invoice_{uuid.uuid4().hex[:12]}"


@dataclass(slots=True, frozen=True)
class InvoiceLineItem:
    """One human-readable invoice line item.

    Example:
        >>> InvoiceLineItem("Agent runs", 2.0, 0.02, 0.04).total_usd
        0.04
    """

    description: str
    quantity: float
    unit_price_usd: float
    total_usd: float


@dataclass(slots=True)
class Invoice:
    """Standalone invoice document generated from metered usage.

    Example:
        >>> Invoice("inv", "tenant-a", 0.0, 1.0, [], 0.0, 0.0, 0.0, "draft", 1.0).status
        'draft'
    """

    invoice_id: str
    tenant_id: str
    period_start: float
    period_end: float
    line_items: list[InvoiceLineItem]
    subtotal_usd: float
    tax_usd: float
    total_usd: float
    status: str
    created_at: float
    tier: str = "free"
    metadata: dict[str, Any] = field(default_factory=dict)


class InvoiceGenerator:
    """Generate human-readable invoices from `UsageMeter` events.

    Example:
        >>> generator = InvoiceGenerator(UsageMeter(path=":memory:"))
        >>> invoice = generator.generate("tenant-a", 0.0, 10.0)
        >>> invoice.tenant_id
        'tenant-a'
    """

    def __init__(
        self,
        meter: UsageMeter,
        *,
        tier_lookup: Callable[[str], str] | None = None,
        tax_rate: float = 0.10,
    ) -> None:
        self.meter = meter
        self.tier_lookup = tier_lookup or (lambda _tenant_id: "free")
        self.tax_rate = max(0.0, float(tax_rate))

    def generate(self, tenant_id: str, period_start: float, period_end: float) -> Invoice:
        """Generate one invoice from metered usage totals.

        Example:
            >>> generator = InvoiceGenerator(UsageMeter(path=":memory:"))
            >>> generator.generate("tenant-a", 0.0, 1.0).subtotal_usd
            0.0
        """

        tier = _normalize_tier(self.tier_lookup(tenant_id))
        line_items: list[InvoiceLineItem] = []
        for metric in SUPPORTED_METRICS:
            quantity = self.meter.aggregate(tenant_id, metric, period_start, period_end)
            if quantity <= 0:
                continue
            unit_price = float(METRIC_PRICES.get(metric, {}).get(tier, 0.0))
            total = round(quantity * unit_price, 6)
            line_items.append(
                InvoiceLineItem(
                    description=_metric_description(metric),
                    quantity=round(quantity, 6),
                    unit_price_usd=unit_price,
                    total_usd=total,
                )
            )
        subtotal = round(sum(line.total_usd for line in line_items), 6)
        tax = round(subtotal * self.tax_rate, 6)
        total = round(subtotal + tax, 6)
        return Invoice(
            invoice_id=_invoice_id(),
            tenant_id=str(tenant_id),
            period_start=float(period_start),
            period_end=float(period_end),
            line_items=line_items,
            subtotal_usd=subtotal,
            tax_usd=tax,
            total_usd=total,
            status="draft",
            created_at=time.time(),
            tier=tier,
            metadata={"metric_prices": METRIC_PRICES},
        )

    def export_pdf(self, invoice: Invoice, path: str | Path) -> Path:
        """Export one invoice to PDF when `reportlab` exists, else plain text fallback.

        Example:
            >>> generator = InvoiceGenerator(UsageMeter(path=":memory:"))
            >>> isinstance(generator.export_pdf(generator.generate("tenant-a", 0.0, 1.0), "invoice.txt"), Path)
            True
        """

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from reportlab.lib.pagesizes import LETTER
            from reportlab.pdfgen import canvas

            pdf = canvas.Canvas(str(output_path), pagesize=LETTER)
            y = 760
            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawString(50, y, f"ARCHON Invoice {invoice.invoice_id}")
            y -= 24
            pdf.setFont("Helvetica", 10)
            pdf.drawString(50, y, f"Tenant: {invoice.tenant_id}")
            y -= 16
            pdf.drawString(50, y, f"Period: {invoice.period_start:.0f} - {invoice.period_end:.0f}")
            y -= 24
            for line in invoice.line_items:
                pdf.drawString(
                    50,
                    y,
                    f"{line.description}: {line.quantity} x ${line.unit_price_usd:.6f} = ${line.total_usd:.6f}",
                )
                y -= 16
            y -= 8
            pdf.drawString(50, y, f"Subtotal: ${invoice.subtotal_usd:.6f}")
            y -= 16
            pdf.drawString(50, y, f"Tax: ${invoice.tax_usd:.6f}")
            y -= 16
            pdf.drawString(50, y, f"Total: ${invoice.total_usd:.6f}")
            pdf.save()
        except Exception:
            lines = [
                f"ARCHON Invoice {invoice.invoice_id}",
                f"Tenant: {invoice.tenant_id}",
                f"Period: {invoice.period_start:.0f} - {invoice.period_end:.0f}",
            ]
            for line in invoice.line_items:
                lines.append(
                    f"{line.description}: {line.quantity} x ${line.unit_price_usd:.6f} = ${line.total_usd:.6f}"
                )
            lines.append(f"Subtotal: ${invoice.subtotal_usd:.6f}")
            lines.append(f"Tax: ${invoice.tax_usd:.6f}")
            lines.append(f"Total: ${invoice.total_usd:.6f}")
            output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return output_path

    def export_json(self, invoice: Invoice, path: str | Path) -> Path:
        """Export one invoice as JSON Lines.

        Example:
            >>> generator = InvoiceGenerator(UsageMeter(path=":memory:"))
            >>> isinstance(generator.export_json(generator.generate("tenant-a", 0.0, 1.0), "invoice.jsonl"), Path)
            True
        """

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"type": "invoice", **_invoice_to_dict(invoice)},
            *[
                {"type": "line_item", **asdict(item), "invoice_id": invoice.invoice_id}
                for item in invoice.line_items
            ],
        ]
        output_path.write_text(
            "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
            encoding="utf-8",
        )
        return output_path


def _normalize_tier(tier: str) -> str:
    normalized = str(tier or "").strip().lower()
    if normalized in {"growth", "business", "pro"}:
        return "pro"
    if normalized == "enterprise":
        return "enterprise"
    return "free"


def _metric_description(metric: str) -> str:
    return str(metric).replace("_", " ").title()


def _invoice_to_dict(invoice: Invoice) -> dict[str, Any]:
    return {
        "invoice_id": invoice.invoice_id,
        "tenant_id": invoice.tenant_id,
        "period_start": invoice.period_start,
        "period_end": invoice.period_end,
        "line_items": [asdict(item) for item in invoice.line_items],
        "subtotal_usd": invoice.subtotal_usd,
        "tax_usd": invoice.tax_usd,
        "total_usd": invoice.total_usd,
        "status": invoice.status,
        "created_at": invoice.created_at,
        "tier": invoice.tier,
        "metadata": dict(invoice.metadata),
    }
