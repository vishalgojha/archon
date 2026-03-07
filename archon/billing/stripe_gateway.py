"""Stripe billing gateway abstraction."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from archon.billing.models import BillingCustomer, BillingInvoice, BillingPlan, BillingSubscription


@dataclass(frozen=True, slots=True)
class StripeMutationResult:
    """Normalized result for one Stripe mutation."""

    external_id: str
    status: str
    payload: dict[str, Any]


class StripeGateway:
    """Sync customers, subscriptions, and invoices to Stripe.

    Example:
        >>> gateway = StripeGateway(api_key="", live_mode=False)
        >>> result = __import__("asyncio").run(gateway.upsert_customer(BillingCustomer(tenant_id="t")))
        >>> result.external_id.startswith("stripe_customer_")
        True
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.stripe.com/v1",
        live_mode: bool = False,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.live_mode = bool(live_mode and self.api_key)
        self._http = httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        """Close the underlying HTTP client.

        Example:
            >>> gateway = StripeGateway(api_key="")
            >>> __import__("asyncio").run(gateway.aclose()) is None
            True
        """

        await self._http.aclose()

    async def upsert_customer(self, customer: BillingCustomer) -> StripeMutationResult:
        """Create or update a Stripe customer."""

        if not self.live_mode:
            identifier = customer.external_customer_id or f"stripe_customer_{uuid.uuid4().hex[:10]}"
            return StripeMutationResult(identifier, "simulated", {"tenant_id": customer.tenant_id})

        data = {
            "email": customer.email,
            "name": customer.name,
            "metadata[tenant_id]": customer.tenant_id,
        }
        if customer.external_customer_id:
            payload = await self._post(f"/customers/{customer.external_customer_id}", data)
            identifier = str(payload.get("id") or customer.external_customer_id)
        else:
            payload = await self._post("/customers", data)
            identifier = str(payload.get("id", ""))
        return StripeMutationResult(identifier, str(payload.get("status") or "active"), payload)

    async def upsert_subscription(
        self,
        customer_external_id: str,
        subscription: BillingSubscription,
        plan: BillingPlan,
    ) -> StripeMutationResult:
        """Create or update a Stripe subscription."""

        if not self.live_mode:
            identifier = (
                subscription.external_subscription_id
                or f"stripe_subscription_{uuid.uuid4().hex[:10]}"
            )
            return StripeMutationResult(identifier, subscription.status, {"plan_id": plan.plan_id})

        data = {
            "customer": customer_external_id,
            "items[0][price_data][currency]": "usd",
            "items[0][price_data][recurring][interval]": "month",
            "items[0][price_data][product_data][name]": f"ARCHON {plan.name}",
            "items[0][price_data][unit_amount_decimal]": int(round(plan.base_monthly_usd * 100)),
            "metadata[tenant_id]": subscription.tenant_id,
            "metadata[plan_id]": plan.plan_id,
        }
        if subscription.external_subscription_id:
            payload = await self._post(f"/subscriptions/{subscription.external_subscription_id}", data)
            identifier = str(payload.get("id") or subscription.external_subscription_id)
        else:
            payload = await self._post("/subscriptions", data)
            identifier = str(payload.get("id", ""))
        return StripeMutationResult(identifier, str(payload.get("status") or "active"), payload)

    async def create_invoice(
        self,
        customer_external_id: str,
        invoice: BillingInvoice,
    ) -> StripeMutationResult:
        """Create a Stripe invoice from the local invoice document."""

        if not self.live_mode:
            identifier = invoice.external_invoice_id or f"stripe_invoice_{uuid.uuid4().hex[:10]}"
            return StripeMutationResult(identifier, "draft", {"total_usd": invoice.total_usd})

        for index, line in enumerate(invoice.lines):
            await self._post(
                "/invoiceitems",
                {
                    "customer": customer_external_id,
                    "currency": invoice.currency,
                    "amount": int(round(line.amount_usd * 100)),
                    "description": line.description,
                    "metadata[line_index]": index,
                    "metadata[meter_type]": line.meter_type,
                },
            )
        payload = await self._post(
            "/invoices",
            {
                "customer": customer_external_id,
                "auto_advance": "false",
                "metadata[tenant_id]": invoice.tenant_id,
                "metadata[invoice_id]": invoice.invoice_id,
            },
        )
        identifier = str(payload.get("id", ""))
        return StripeMutationResult(identifier, str(payload.get("status") or "draft"), payload)

    async def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = await self._http.post(f"{self.base_url}{path}", headers=headers, data=data)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
