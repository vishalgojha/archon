"""Regression tests for HTTP auth middleware settings resolution."""

from __future__ import annotations

import httpx
import jwt
import pytest
from fastapi import FastAPI, Request

from archon.interfaces.api.auth import AuthMiddleware, AuthSettings


def _auth_headers(secret: str) -> dict[str, str]:
    token = jwt.encode(
        {"sub": "tenant-http-auth", "tier": "pro"},
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        AuthMiddleware,
        settings=AuthSettings(secret="bootstrap-secret-does-not-match-32-bytes"),
    )

    @app.get("/probe")
    async def probe(request: Request) -> dict[str, str]:
        return {"tenant_id": request.state.auth.tenant_id}

    return app


def test_auth_settings_from_env_strip_surrounding_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "  secret-value  ")
    monkeypatch.setenv("ARCHON_JWT_ALGORITHM", "  HS256  ")
    monkeypatch.setenv("ARCHON_JWT_ISSUER", "  issuer-a  ")
    monkeypatch.setenv("ARCHON_JWT_AUDIENCE", "  audience-a  ")

    settings = AuthSettings.from_env()

    assert settings == AuthSettings(
        secret="secret-value",
        algorithm="HS256",
        issuer="issuer-a",
        audience="audience-a",
    )


async def test_http_middleware_uses_lifespan_auth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    rotated_secret = "rotated-http-secret-012345678901234567890123"
    monkeypatch.setenv("ARCHON_JWT_SECRET", rotated_secret)

    app = _build_test_app()
    app.state.auth_settings = AuthSettings.from_env()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/probe", headers=_auth_headers(rotated_secret))

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-http-auth"
