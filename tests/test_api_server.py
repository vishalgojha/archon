"""API contract tests for the minimal ARCHON runtime."""

from __future__ import annotations

from pathlib import Path

import jwt
import pytest

from archon.interfaces.api.rate_limit import InMemoryTierRateLimitStore, set_rate_limit_store
from archon.interfaces.api.server import app
from archon.testing import lifespan, request
from archon.versioning import resolve_git_sha

pytestmark = pytest.mark.asyncio


def _auth_headers(*, tenant: str = "tenant-test", tier: str = "pro") -> dict[str, str]:
    token = jwt.encode(
        {"sub": tenant, "tier": tier},
        "archon-dev-secret-change-me-32-bytes",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _auth_token(*, tenant: str = "tenant-test", tier: str = "pro") -> str:
    return jwt.encode(
        {"sub": tenant, "tier": tier},
        "archon-dev-secret-change-me-32-bytes",
        algorithm="HS256",
    )


async def test_post_tasks_rejects_missing_bearer_token() -> None:
    async with lifespan(app):
        response = await request(
            app,
            "POST",
            "/v1/tasks",
            json_body={"goal": "Any goal", "mode": "debate"},
        )
    assert response.status_code == 401


async def test_post_tasks_debate_mode_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")

    async with lifespan(app):
        response = await request(
            app,
            "POST",
            "/v1/tasks",
            json_body={
                "goal": "Draft a migration rollout plan",
                "mode": "debate",
            },
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "debate"
    assert payload["debate"] is not None
    assert isinstance(payload["debate"]["rounds"], list)
    assert len(payload["debate"]["rounds"]) == 6
    assert isinstance(payload["budget"], dict)
    assert isinstance(payload["confidence"], int)


async def test_post_tasks_applies_tier_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")

    previous_store = app.state.rate_limit_store
    app.state.rate_limit_store = InMemoryTierRateLimitStore(
        limits={
            "free": "2/minute",
            "pro": "100/minute",
            "enterprise": "100/minute",
        }
    )
    set_rate_limit_store(app.state.rate_limit_store)
    try:
        async with lifespan(app):
            headers = _auth_headers(tenant="tenant-free-limit", tier="free")
            body = {"goal": "Draft summary", "mode": "debate"}
            first = await request(app, "POST", "/v1/tasks", json_body=body, headers=headers)
            second = await request(app, "POST", "/v1/tasks", json_body=body, headers=headers)
            third = await request(app, "POST", "/v1/tasks", json_body=body, headers=headers)
    finally:
        app.state.rate_limit_store = previous_store
        set_rate_limit_store(previous_store)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


async def test_health_endpoint_returns_status_version_and_uptime() -> None:
    async with lifespan(app):
        response = await request(app, "GET", "/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == app.version
    assert payload["git_sha"] == resolve_git_sha()
    assert isinstance(payload["uptime_s"], (int, float))
    assert payload["uptime_s"] >= 0


async def test_shell_route_serves_index() -> None:
    async with lifespan(app):
        response = await request(app, "GET", "/shell")

    assert response.status_code == 200
    assert "ARCHON" in response.text


async def test_ui_pack_build_register_activate_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")
    token = _auth_token(tenant="tenant-ui", tier="pro")

    async with lifespan(app):
        build = await request(
            app,
            "POST",
            "/v1/ui-packs/build",
            json_body={"version": "v1", "blueprint": {}, "auto_approve": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        register = await request(
            app,
            "POST",
            "/v1/ui-packs/register",
            json_body={"version": "v1", "auto_approve": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        activate = await request(
            app,
            "POST",
            "/v1/ui-packs/activate",
            json_body={"version": "v1", "auto_approve": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        active = await request(
            app,
            "GET",
            "/v1/ui-packs/active",
            headers={"Authorization": f"Bearer {token}"},
        )
        asset = await request(
            app,
            "GET",
            "/ui-packs/v1/index.js",
            params={"token": token},
        )

    assert build.status_code == 200
    assert register.status_code == 200
    assert activate.status_code == 200
    assert active.status_code == 200
    assert active.json()["active"]["version"] == "v1"
    assert asset.status_code == 200


async def test_issue_session_token_rejects_when_auth_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")

    async with lifespan(app):
        response = await request(
            app,
            "POST",
            "/v1/auth/session-token",
            json_body={"tenant_id": "session-user", "tier": "pro"},
            base_url="http://127.0.0.1",
            headers=_auth_headers(),
        )

    assert response.status_code == 403


async def test_issue_session_token_requires_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARCHON_JWT_SECRET", raising=False)

    async with lifespan(app):
        response = await request(
            app,
            "POST",
            "/v1/auth/session-token",
            json_body={"tenant_id": "session-user", "tier": "pro"},
            base_url="http://example.com",
        )

    assert response.status_code == 403


async def test_issue_session_token_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARCHON_JWT_SECRET", raising=False)

    async with lifespan(app):
        response = await request(
            app,
            "POST",
            "/v1/auth/session-token",
            json_body={"tenant_id": "session-user", "tier": "pro"},
            base_url="http://127.0.0.1",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "session-user"
    assert payload["tier"] == "pro"
    assert payload["ephemeral"] is True
    assert isinstance(payload["token"], str)


async def test_list_pending_approvals_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")

    async with lifespan(app):
        response = await request(
            app,
            "GET",
            "/v1/approvals",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    assert response.json() == {"approvals": []}


async def test_approve_and_deny_unknown_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")
    token = _auth_token()

    async with lifespan(app):
        approve = await request(
            app,
            "POST",
            "/v1/approvals/unknown/approve",
            json_body={},
            headers={"Authorization": f"Bearer {token}"},
        )
        deny = await request(
            app,
            "POST",
            "/v1/approvals/unknown/deny",
            json_body={},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert approve.status_code == 404
    assert deny.status_code == 404


async def test_ui_pack_versions_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")
    token = _auth_token(tenant="tenant-ui-empty", tier="pro")

    async with lifespan(app):
        response = await request(
            app,
            "GET",
            "/v1/ui-packs/versions",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json() == {"versions": []}


async def test_ui_pack_asset_requires_token() -> None:
    async with lifespan(app):
        response = await request(app, "GET", "/ui-packs/v1/index.js")

    assert response.status_code == 401


async def test_brain_write_accepts_valid_module_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")
    monkeypatch.setenv("ARCHON_BRAIN_ROOT", str(tmp_path))
    payload = {
        "artifact": "module_registry",
        "schema_version": "v1",
        "agent_id": "planner_agent",
        "payload": {
            "version": "2026.03.17",
            "modules": [
                {
                    "id": "core.brain",
                    "name": "Brain Core",
                    "owner": "planner_agent",
                    "status": "active",
                    "dependencies": ["core.orchestrator"],
                }
            ],
        },
    }

    async with lifespan(app):
        response = await request(
            app,
            "POST",
            "/brain/write",
            json_body=payload,
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["authoritative"] is True
    assert Path(body["path"]).exists()


async def test_brain_write_rejects_unauthorized_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")
    monkeypatch.setenv("ARCHON_BRAIN_ROOT", str(tmp_path))
    payload = {
        "artifact": "module_registry",
        "schema_version": "v1",
        "agent_id": "random_agent",
        "payload": {"modules": []},
    }

    async with lifespan(app):
        response = await request(
            app,
            "POST",
            "/brain/write",
            json_body=payload,
            headers=_auth_headers(),
        )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "unauthorized_agent"


async def test_brain_write_rejects_schema_violation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")
    monkeypatch.setenv("ARCHON_BRAIN_ROOT", str(tmp_path))
    payload = {
        "artifact": "module_registry",
        "schema_version": "v1",
        "agent_id": "planner_agent",
        "payload": {"version": "2026.03.17"},
    }

    async with lifespan(app):
        response = await request(
            app,
            "POST",
            "/brain/write",
            json_body=payload,
            headers=_auth_headers(),
        )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "schema_validation_error"
    assert body["error"]["errors"]


async def test_brain_snapshot_writes_delta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")
    monkeypatch.setenv("ARCHON_BRAIN_ROOT", str(tmp_path))
    payload = {
        "artifact": "delta",
        "payload": {"diff": ["added core.brain"]},
    }

    async with lifespan(app):
        response = await request(
            app,
            "POST",
            "/brain/snapshot",
            json_body=payload,
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["authoritative"] is False
    assert Path(body["path"]).exists()
