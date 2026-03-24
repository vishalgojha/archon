"""Tests for tenant auth, feature gating, and sliding-window rate limits."""

from __future__ import annotations

from collections.abc import Generator

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from archon.api import auth as auth_module


@pytest.fixture
def auth_app(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[FastAPI, auth_module.RateLimiter], None, None]:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "test-secret")
    previous = auth_module.get_rate_limiter()
    limiter = auth_module.RateLimiter()
    auth_module.set_rate_limiter(limiter)

    app = FastAPI()

    @app.get("/secure")
    async def secure(
        tenant: auth_module.TenantContext = Depends(auth_module.require_tenant),
    ) -> dict[str, str]:
        return {
            "tenant_id": tenant.tenant_id,
            "tier": tenant.tier,
            "memory_ns": tenant.memory_namespace,
            "audit_ns": tenant.audit_namespace,
            "keys_ns": tenant.keys_namespace,
        }

    @app.get("/optional")
    async def optional(
        tenant: auth_module.TenantContext | None = Depends(auth_module.optional_tenant),
    ) -> dict[str, str | None]:
        if tenant is None:
            return {"tenant_id": None}
        return {"tenant_id": tenant.tenant_id}

    try:
        yield app, limiter
    finally:
        auth_module.set_rate_limiter(previous)


@pytest.mark.parametrize("tier", ["free", "pro", "enterprise"])
def test_token_round_trip_all_tiers(monkeypatch: pytest.MonkeyPatch, tier: str) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "test-secret")
    token = auth_module.create_tenant_token("tenant-a", tier)  # type: ignore[arg-type]
    payload = auth_module.verify_tenant_token(token)
    context = auth_module.tenant_context_from_token(token)

    assert payload["sub"] == "tenant-a"
    assert payload["tier"] == tier
    assert payload["type"] == "tenant"
    assert context.tenant_id == "tenant-a"
    assert context.tier == tier
    assert context.rate_limit_per_minute == auth_module.TIER_RATE_LIMITS[tier]  # type: ignore[index]


def test_tampered_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "test-secret")
    token = auth_module.create_tenant_token("tenant-a", "pro")
    header, payload, signature = token.split(".")
    tampered_signature = ("a" if signature[0] != "a" else "b") + signature[1:]
    tampered = ".".join([header, payload, tampered_signature])

    with pytest.raises(auth_module.TenantTokenError):
        auth_module.verify_tenant_token(tampered)


def test_expired_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "test-secret")
    token = auth_module.create_tenant_token("tenant-a", "pro", expires_in_seconds=-1)

    with pytest.raises(auth_module.TenantTokenError):
        auth_module.verify_tenant_token(token)


def test_wrong_type_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "test-secret")
    token = jwt.encode(
        {
            "sub": "tenant-a",
            "tier": "pro",
            "iat": 1_700_000_000,
            "exp": 2_200_000_000,
            "type": "service",
        },
        "test-secret",
        algorithm="HS256",
    )

    with pytest.raises(auth_module.TenantTokenError):
        auth_module.verify_tenant_token(token)


def test_tenant_context_feature_gating() -> None:
    free_ctx = auth_module.TenantContext("tenant-free", "free", 10)
    enterprise_ctx = auth_module.TenantContext("tenant-ent", "enterprise", 1000)

    assert free_ctx.can_use_feature("debate") is True
    assert enterprise_ctx.can_use_feature("ui_pack") is True


def test_rate_limiter_allows_within_limit_and_blocks_at_limit() -> None:
    limiter = auth_module.RateLimiter(clock=lambda: 1000.0)

    assert limiter.allow("tenant-a", 2) is True
    assert limiter.allow("tenant-a", 2) is True
    assert limiter.allow("tenant-a", 2) is False


def test_rate_limiter_tenants_are_independent() -> None:
    limiter = auth_module.RateLimiter(clock=lambda: 1000.0)

    assert limiter.allow("tenant-a", 1) is True
    assert limiter.allow("tenant-a", 1) is False
    assert limiter.allow("tenant-b", 1) is True


def test_rate_limiter_reset_clears_counter() -> None:
    limiter = auth_module.RateLimiter(clock=lambda: 1000.0)

    assert limiter.allow("tenant-a", 1) is True
    assert limiter.allow("tenant-a", 1) is False
    limiter.reset("tenant-a")
    assert limiter.allow("tenant-a", 1) is True


def test_dependency_accepts_valid_bearer(auth_app: tuple[FastAPI, auth_module.RateLimiter]) -> None:
    app, _limiter = auth_app
    token = auth_module.create_tenant_token("tenant-bearer", "free", secret="test-secret")

    with TestClient(app) as client:
        response = client.get("/secure", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-bearer"


def test_dependency_accepts_valid_archon_key_header(
    auth_app: tuple[FastAPI, auth_module.RateLimiter],
) -> None:
    app, _limiter = auth_app
    token = auth_module.create_tenant_token("tenant-key", "pro", secret="test-secret")

    with TestClient(app) as client:
        response = client.get("/secure", headers={"X-Archon-Key": token})

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-key"


def test_dependency_missing_token_returns_401(
    auth_app: tuple[FastAPI, auth_module.RateLimiter],
) -> None:
    app, _limiter = auth_app
    with TestClient(app) as client:
        response = client.get("/secure")

    assert response.status_code == 401


def test_dependency_rate_limited_returns_429(
    auth_app: tuple[FastAPI, auth_module.RateLimiter],
) -> None:
    app, limiter = auth_app
    tenant_id = "tenant-rate-limit"
    for _ in range(auth_module.TIER_RATE_LIMITS["free"]):
        assert limiter.allow(tenant_id, auth_module.TIER_RATE_LIMITS["free"]) is True

    token = auth_module.create_tenant_token(tenant_id, "free", secret="test-secret")
    with TestClient(app) as client:
        response = client.get("/secure", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 429
