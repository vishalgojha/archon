"""API tests for billing routes, tenant isolation, and approval behavior."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import jwt
import pytest

from archon.interfaces.api.server import app
from archon.testing.asgi import lifespan, request

pytestmark = pytest.mark.asyncio


def _auth_headers(*, tenant: str = "tenant-a", tier: str = "business") -> dict[str, str]:
    token = jwt.encode(
        {"sub": tenant, "tier": tier},
        "archon-dev-secret-change-me-32-bytes",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _tmp_db(name: str) -> Path:
    root = Path("tests/_tmp_billing_api")
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{name}-{uuid.uuid4().hex[:8]}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "db.sqlite3"


async def test_billing_summary_rejects_cross_tenant_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_BILLING_DB", str(_tmp_db("isolation")))
    monkeypatch.setenv("ARCHON_ANALYTICS_DB", str(_tmp_db("analytics")))

    async with lifespan(app):
        response = await request(
            app,
            "GET",
            "/v1/billing/summary",
            params={"tenant_id": "tenant-b"},
            headers=_auth_headers(tenant="tenant-a", tier="business"),
        )

    assert response.status_code == 403


async def test_enterprise_admin_can_manage_other_tenant_and_generate_invoice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARCHON_BILLING_DB", str(_tmp_db("enterprise")))
    monkeypatch.setenv("ARCHON_ANALYTICS_DB", str(_tmp_db("analytics")))

    async with lifespan(app):
        customer = await request(
            app,
            "POST",
            "/v1/billing/customer",
            json_body={"tenant_id": "tenant-b", "email": "owner@example.com"},
            headers=_auth_headers(tenant="ops-root", tier="enterprise"),
        )
        subscription = await request(
            app,
            "POST",
            "/v1/billing/subscription",
            json_body={"tenant_id": "tenant-b", "plan_id": "growth"},
            headers=_auth_headers(tenant="ops-root", tier="enterprise"),
        )
        usage = await request(
            app,
            "POST",
            "/v1/billing/usage",
            json_body={
                "tenant_id": "tenant-b",
                "meter_type": "model_spend",
                "quantity": 1,
                "amount_usd": 30,
                "provider": "openai",
                "model": "gpt-4o",
            },
            headers=_auth_headers(tenant="ops-root", tier="enterprise"),
        )
        invoice = await request(
            app,
            "POST",
            "/v1/billing/invoices/generate",
            json_body={"tenant_id": "tenant-b"},
            headers=_auth_headers(tenant="ops-root", tier="enterprise"),
        )
        summary = await request(
            app,
            "GET",
            "/v1/billing/summary",
            params={"tenant_id": "tenant-b"},
            headers=_auth_headers(tenant="ops-root", tier="enterprise"),
        )

    assert customer.status_code == 200
    assert subscription.status_code == 200
    assert usage.status_code == 200
    assert invoice.status_code == 200
    assert invoice.json()["invoice"]["total_usd"] == 54.0
    assert summary.json()["usage_summary"]["model_spend_usd"] == 30.0


async def test_billing_external_sync_requires_approval_then_auto_approve_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARCHON_BILLING_DB", str(_tmp_db("approval")))
    monkeypatch.setenv("ARCHON_ANALYTICS_DB", str(_tmp_db("analytics")))
    monkeypatch.setenv("ARCHON_STRIPE_SECRET_KEY", "sk_test_123")

    async with lifespan(app):
        blocked = await request(
            app,
            "POST",
            "/v1/billing/customer",
            json_body={"email": "owner@example.com", "sync_external": True},
            headers=_auth_headers(),
        )
        approved = await request(
            app,
            "POST",
            "/v1/billing/customer",
            json_body={"email": "owner@example.com", "sync_external": True, "auto_approve": True},
            headers=_auth_headers(),
        )

    assert blocked.status_code == 409
    assert approved.status_code == 200
    assert approved.json()["customer"]["external_customer_id"].startswith("stripe_customer_")
