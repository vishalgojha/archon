"""Regression tests for HTTP auth middleware settings resolution."""

from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from archon.interfaces.api.auth import AuthSettings
from archon.interfaces.api.server import app


def _auth_headers(secret: str) -> dict[str, str]:
    token = jwt.encode(
        {"sub": "tenant-http-auth", "tier": "business"},
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


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


def test_http_middleware_uses_lifespan_auth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    rotated_secret = "rotated-http-secret-012345678901234567890123"
    monkeypatch.setenv("ARCHON_JWT_SECRET", rotated_secret)

    with TestClient(app) as client:
        response = client.get("/console/providers/validate", headers=_auth_headers(rotated_secret))

    assert response.status_code == 200
    assert "providers" in response.json()
