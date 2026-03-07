"""Billing API router for tenant-scoped billing operations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from archon.billing import BillingService
from archon.core.approval_gate import ApprovalDeniedError, ApprovalRequiredError


class BillingCustomerRequest(BaseModel):
    tenant_id: str | None = None
    email: str = ""
    name: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    sync_external: bool = False
    auto_approve: bool = False


class BillingSubscriptionRequest(BaseModel):
    tenant_id: str | None = None
    plan_id: str = Field(min_length=1)
    effective_at: float | None = None
    sync_external: bool = False
    auto_approve: bool = False


class BillingUsageRequest(BaseModel):
    tenant_id: str | None = None
    meter_type: str = Field(min_length=1)
    quantity: float = Field(gt=0.0)
    amount_usd: float = Field(ge=0.0)
    provider: str = ""
    model: str = ""
    action_type: str = ""
    task_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: float | None = None


class BillingInvoiceRequest(BaseModel):
    tenant_id: str | None = None
    period_start: float | None = None
    period_end: float | None = None
    sync_external: bool = False
    auto_approve: bool = False


router = APIRouter(prefix="/v1/billing", tags=["billing"])


@router.get("/plans")
async def billing_plans(request: Request) -> dict[str, Any]:
    """Return the billing plan catalog."""

    service = _service(request)
    return {"plans": service.plans()}


@router.get("/summary")
async def billing_summary(
    request: Request,
    tenant_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return billing summary for the authenticated tenant or an enterprise-selected tenant."""

    scoped_tenant = _tenant_scope(request, tenant_id)
    service = _service(request)
    return service.summary(scoped_tenant)


@router.get("/invoices")
async def billing_invoices(
    request: Request,
    tenant_id: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    """List recent invoices for one tenant."""

    scoped_tenant = _tenant_scope(request, tenant_id)
    service = _service(request)
    return {"invoices": [_payload(row) for row in service.store.list_invoices(scoped_tenant, limit=limit)]}


@router.post("/customer")
async def billing_upsert_customer(
    request: Request,
    payload: BillingCustomerRequest,
) -> dict[str, Any]:
    """Create or update one billing customer."""

    scoped_tenant = _tenant_scope(request, payload.tenant_id)
    service = _service(request)
    sink = _approval_sink(request, payload.auto_approve)
    try:
        customer = await service.upsert_customer(
            tenant_id=scoped_tenant,
            email=payload.email,
            name=payload.name,
            metadata=payload.metadata,
            sync_external=payload.sync_external,
            event_sink=sink,
        )
    except ApprovalRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ApprovalDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"status": "ok", "customer": _payload(customer)}


@router.post("/subscription")
async def billing_change_subscription(
    request: Request,
    payload: BillingSubscriptionRequest,
) -> dict[str, Any]:
    """Create or change one tenant subscription."""

    scoped_tenant = _tenant_scope(request, payload.tenant_id)
    service = _service(request)
    sink = _approval_sink(request, payload.auto_approve)
    try:
        subscription = await service.change_subscription(
            tenant_id=scoped_tenant,
            plan_id=payload.plan_id,
            effective_at=payload.effective_at,
            sync_external=payload.sync_external,
            event_sink=sink,
        )
    except ApprovalRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ApprovalDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"status": "ok", "subscription": _payload(subscription)}


@router.post("/usage")
async def billing_record_usage(
    request: Request,
    payload: BillingUsageRequest,
) -> dict[str, Any]:
    """Append one usage record for the scoped tenant."""

    scoped_tenant = _tenant_scope(request, payload.tenant_id)
    service = _service(request)
    row = await service.record_usage(
        tenant_id=scoped_tenant,
        meter_type=payload.meter_type,
        quantity=payload.quantity,
        amount_usd=payload.amount_usd,
        provider=payload.provider,
        model=payload.model,
        action_type=payload.action_type,
        task_id=payload.task_id,
        metadata=payload.metadata,
        timestamp=payload.timestamp,
    )
    return {"status": "ok", "usage": _payload(row)}


@router.post("/invoices/generate")
async def billing_generate_invoice(
    request: Request,
    payload: BillingInvoiceRequest,
) -> dict[str, Any]:
    """Generate one invoice for the scoped tenant."""

    scoped_tenant = _tenant_scope(request, payload.tenant_id)
    service = _service(request)
    sink = _approval_sink(request, payload.auto_approve)
    try:
        invoice = await service.generate_invoice(
            tenant_id=scoped_tenant,
            period_start=payload.period_start,
            period_end=payload.period_end,
            sync_external=payload.sync_external,
            event_sink=sink,
        )
    except ApprovalRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ApprovalDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"status": "ok", "invoice": _payload(invoice)}


@router.post("/webhooks/stripe")
async def billing_stripe_webhook(request: Request) -> dict[str, Any]:
    """Verify and apply an incoming Stripe webhook."""

    service = _service(request)
    signature = request.headers.get("stripe-signature", "")
    payload = (await request.body()).decode("utf-8")
    try:
        return await service.handle_stripe_webhook(payload, signature)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def create_router() -> APIRouter:
    """Factory helper for mounting the billing router."""

    return router


def _service(request: Request) -> BillingService:
    service = getattr(request.app.state, "billing_service", None)
    if not isinstance(service, BillingService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing service is unavailable.",
        )
    return service


def _tenant_scope(request: Request, requested_tenant_id: str | None) -> str:
    auth = getattr(request.state, "auth", None)
    tenant_id = str(requested_tenant_id or getattr(auth, "tenant_id", "")).strip()
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing authenticated tenant.")
    if getattr(auth, "tier", "") == "enterprise":
        return tenant_id
    if tenant_id != getattr(auth, "tenant_id", ""):
        raise HTTPException(status_code=403, detail="Tenant mismatch.")
    return tenant_id


def _approval_sink(request: Request, auto_approve: bool):
    if not auto_approve:
        return None
    service = _service(request)
    approver = request.state.auth.tenant_id

    async def sink(event: dict[str, Any]) -> None:
        if event.get("type") == "approval_required":
            service.approval_gate.approve(
                str(event["request_id"]),
                approver=approver,
                notes="Auto-approved by authenticated operator via REST.",
            )

    return sink


def _payload(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _payload(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, list):
        return [_payload(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _payload(item) for key, item in value.items()}
    return value
