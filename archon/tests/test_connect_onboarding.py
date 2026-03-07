"""Tests for Stripe Connect onboarding and developer onboarding APIs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from archon.interfaces.api.server import app
from archon.marketplace.connect import (
    ConnectAccount,
    DeveloperOnboarding,
    StripeConnectClient,
    decrypt_partner_account_id,
)
from archon.partners.registry import PartnerRegistry


def _auth_headers(*, tenant: str = "tenant-test", tier: str = "business") -> dict[str, str]:
    token = jwt.encode(
        {"sub": tenant, "tier": tier},
        "archon-dev-secret-change-me-32-bytes",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def _marketplace_envs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")
    monkeypatch.setenv("ARCHON_PARTNERS_DB", str(tmp_path / "partners.sqlite3"))
    monkeypatch.setenv(
        "ARCHON_MARKETPLACE_CONNECT_DB",
        str(tmp_path / "marketplace-connect.sqlite3"),
    )
    monkeypatch.setenv(
        "ARCHON_MARKETPLACE_REVENUE_DB",
        str(tmp_path / "marketplace-revenue.sqlite3"),
    )
    monkeypatch.setenv(
        "ARCHON_MARKETPLACE_CYCLE_DB",
        str(tmp_path / "marketplace-cycles.sqlite3"),
    )


class _FakeStripeClient:
    def __init__(self) -> None:
        self.account_counter = 0
        self.link_counter = 0
        self.accounts: dict[str, ConnectAccount] = {}

    async def create_account(self, email: str, country: str, business_type: str) -> ConnectAccount:
        self.account_counter += 1
        account = ConnectAccount(
            account_id=f"acct_{self.account_counter}",
            email=email,
            country=country,
            charges_enabled=False,
            payouts_enabled=False,
            details_submitted=False,
            created_at=float(self.account_counter),
        )
        self.accounts[account.account_id] = account
        assert business_type == "individual"
        return account

    async def create_account_link(
        self,
        account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> str:
        self.link_counter += 1
        assert refresh_url
        assert return_url
        return f"https://connect.example/{account_id}/{self.link_counter}"

    async def get_account(self, account_id: str) -> ConnectAccount:
        return self.accounts[account_id]


@pytest.mark.asyncio
async def test_create_account_posts_correct_body_and_returns_connect_account() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["body"] = request.content.decode()
        captured["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(
            200,
            json={
                "id": "acct_test_123",
                "email": "dev@example.com",
                "country": "US",
                "charges_enabled": False,
                "payouts_enabled": False,
                "details_submitted": False,
                "created": 1700000000,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = StripeConnectClient(secret_key="sk_test_123", http_client=http_client)
        account = await client.create_account("dev@example.com", "us", "company")

    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer sk_test_123"
    assert "type=express" in captured["body"]
    assert "email=dev%40example.com" in captured["body"]
    assert "country=US" in captured["body"]
    assert "business_type=company" in captured["body"]
    assert account.account_id == "acct_test_123"
    assert account.email == "dev@example.com"


@pytest.mark.asyncio
async def test_create_account_link_returns_url_string() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "account=acct_test_123" in request.content.decode()
        return httpx.Response(200, json={"url": "https://connect.example/onboard/acct_test_123"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = StripeConnectClient(secret_key="sk_test_123", http_client=http_client)
        url = await client.create_account_link(
            "acct_test_123",
            "https://archon.local/refresh",
            "https://archon.local/return",
        )

    assert url == "https://connect.example/onboard/acct_test_123"


@pytest.mark.asyncio
async def test_onboard_creates_stripe_account_stores_account_id_and_returns_url(
    tmp_path: Path,
) -> None:
    registry = PartnerRegistry(path=tmp_path / "partners.sqlite3")
    partner = registry.register("Partner One", "one@example.com", "affiliate")
    stripe_client = _FakeStripeClient()
    onboarding = DeveloperOnboarding(
        registry=registry,
        stripe_client=stripe_client,  # type: ignore[arg-type]
        path=tmp_path / "connect.sqlite3",
    )

    session = await onboarding.onboard(partner.partner_id, partner.email)
    stored = registry.get(partner.partner_id)

    assert session.partner_id == partner.partner_id
    assert session.account_id == "acct_1"
    assert session.onboarding_url.endswith("/acct_1/1")
    assert stored is not None
    assert decrypt_partner_account_id(stored) == "acct_1"


@pytest.mark.asyncio
async def test_complete_updates_partner_to_active_when_stripe_is_ready(tmp_path: Path) -> None:
    registry = PartnerRegistry(path=tmp_path / "partners.sqlite3")
    partner = registry.register("Partner Two", "two@example.com", "affiliate")
    stripe_client = _FakeStripeClient()
    onboarding = DeveloperOnboarding(
        registry=registry,
        stripe_client=stripe_client,  # type: ignore[arg-type]
        path=tmp_path / "connect.sqlite3",
    )

    session = await onboarding.onboard(partner.partner_id, partner.email)
    stripe_client.accounts[session.account_id] = ConnectAccount(
        account_id=session.account_id,
        email=partner.email,
        country="US",
        charges_enabled=True,
        payouts_enabled=True,
        details_submitted=True,
        created_at=1.0,
    )

    assert await onboarding.complete(partner.partner_id) is True
    assert registry.get(partner.partner_id).status == "active"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_complete_leaves_partner_pending_when_stripe_not_ready(tmp_path: Path) -> None:
    registry = PartnerRegistry(path=tmp_path / "partners.sqlite3")
    partner = registry.register("Partner Three", "three@example.com", "affiliate")
    stripe_client = _FakeStripeClient()
    onboarding = DeveloperOnboarding(
        registry=registry,
        stripe_client=stripe_client,  # type: ignore[arg-type]
        path=tmp_path / "connect.sqlite3",
    )

    session = await onboarding.onboard(partner.partner_id, partner.email)
    stripe_client.accounts[session.account_id] = ConnectAccount(
        account_id=session.account_id,
        email=partner.email,
        country="US",
        charges_enabled=False,
        payouts_enabled=False,
        details_submitted=True,
        created_at=1.0,
    )

    assert await onboarding.complete(partner.partner_id) is False
    assert registry.get(partner.partner_id).status == "pending"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_expired_session_refresh_creates_new_onboarding_session(tmp_path: Path) -> None:
    registry = PartnerRegistry(path=tmp_path / "partners.sqlite3")
    partner = registry.register("Partner Four", "four@example.com", "affiliate")
    stripe_client = _FakeStripeClient()
    onboarding = DeveloperOnboarding(
        registry=registry,
        stripe_client=stripe_client,  # type: ignore[arg-type]
        path=tmp_path / "connect.sqlite3",
    )

    original = await onboarding.onboard(partner.partner_id, partner.email)
    with sqlite3.connect(tmp_path / "connect.sqlite3") as conn:
        conn.execute(
            "UPDATE onboarding_sessions SET expires_at = ? WHERE session_id = ?",
            (0.0, original.session_id),
        )

    refreshed = await onboarding.refresh(partner.partner_id)

    assert refreshed.session_id != original.session_id
    assert refreshed.onboarding_url != original.onboarding_url


def test_api_post_onboard_requires_enterprise_token(
    _marketplace_envs: None,
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/marketplace/developers/onboard",
            json={
                "partner_id": "partner-1",
                "email": "dev@example.com",
                "country": "US",
            },
            headers=_auth_headers(tenant="tenant-free", tier="free"),
        )

    assert response.status_code == 401
