"""API contract tests for tenant memory import endpoint."""

from __future__ import annotations

import asyncio
from pathlib import Path

import jwt

from archon.interfaces.api.server import app
from archon.testing.asgi import lifespan, request


def _auth_headers(*, tenant: str = "tenant-a", tier: str = "enterprise") -> dict[str, str]:
    token = jwt.encode(
        {"sub": tenant, "tier": tier},
        "archon-dev-secret-change-me-32-bytes",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_v1_memory_import_requires_tenant_match(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")
    monkeypatch.setenv("ARCHON_MEMORY_DB", str(tmp_path / "memory.sqlite3"))

    async def _run() -> None:
        async with lifespan(app):
            response = await request(
                app,
                "POST",
                "/v1/memory/import",
                json_body={"tenant_id": "tenant-other", "entries": []},
                headers=_auth_headers(tenant="tenant-a"),
            )
            assert response.status_code == 403

    asyncio.run(_run())


def test_v1_memory_import_inserts_entries(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ARCHON_JWT_SECRET", "archon-dev-secret-change-me-32-bytes")
    monkeypatch.setenv("ARCHON_MEMORY_DB", str(tmp_path / "memory.sqlite3"))

    entry = {
        "memory_id": "mem-1",
        "timestamp": 1710000000.0,
        "content": "hello",
        "role": "assistant",
        "session_id": "session-1",
        "tenant_id": "tenant-a",
        "embedding": [0.0, 0.0, 0.0],
        "metadata": {"source": "test"},
        "forgotten": False,
    }

    async def _run() -> None:
        async with lifespan(app):
            response = await request(
                app,
                "POST",
                "/v1/memory/import",
                json_body={"tenant_id": "tenant-a", "entries": [entry], "on_conflict": "skip"},
                headers=_auth_headers(tenant="tenant-a"),
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "ok"
            assert payload["imported"] == 1

            # Second time (skip) should skip.
            second = await request(
                app,
                "POST",
                "/v1/memory/import",
                json_body={"tenant_id": "tenant-a", "entries": [entry], "on_conflict": "skip"},
                headers=_auth_headers(tenant="tenant-a"),
            )
            assert second.status_code == 200
            assert second.json()["imported"] == 0

            overwrite = await request(
                app,
                "POST",
                "/v1/memory/import",
                json_body={
                    "tenant_id": "tenant-a",
                    "entries": [dict(entry, content="updated")],
                    "on_conflict": "overwrite",
                },
                headers=_auth_headers(tenant="tenant-a"),
            )
            assert overwrite.status_code == 200
            assert overwrite.json()["replaced"] == 1

    asyncio.run(_run())
