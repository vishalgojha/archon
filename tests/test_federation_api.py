"""Contract tests for federation peer/pattern endpoints."""

from __future__ import annotations

import asyncio

import pytest

from archon.federation.auth import json_bytes, signed_headers
from archon.interfaces.api.server import app
from archon.testing.asgi import lifespan, request


def test_federation_announce_and_list_peers_is_public() -> None:
    async def _run() -> None:
        async with lifespan(app):
            announce = await request(
                app,
                "POST",
                "/federation/announce",
                json_body={
                    "peer_id": "peer-1",
                    "address": "https://peer-1.example.com",
                    "capabilities": ["debate", "vision"],
                    "timestamp": 1710000000.0,
                    "version": "1.2.3",
                    "public_key": "pk-1",
                },
            )
            assert announce.status_code == 200
            payload = announce.json()
            assert payload["status"] == "ok"
            assert payload["peer_id"] == "peer-1"

            peers = await request(app, "GET", "/federation/peers")
            assert peers.status_code == 200
            peers_payload = peers.json()
            peer_ids = {row["peer_id"] for row in peers_payload["peers"]}
            assert "peer-1" in peer_ids

    asyncio.run(_run())


def test_federation_announce_rejects_invalid_address() -> None:
    async def _run() -> None:
        async with lifespan(app):
            response = await request(
                app,
                "POST",
                "/federation/announce",
                json_body={
                    "peer_id": "peer-bad",
                    "address": "ftp://bad.example.com",
                    "capabilities": [],
                },
            )
            assert response.status_code == 422

    asyncio.run(_run())


def test_federation_patterns_round_trip_and_list_is_public() -> None:
    async def _run() -> None:
        async with lifespan(app):
            response = await request(
                app,
                "POST",
                "/federation/patterns",
                json_body={
                    "pattern_id": "p-1",
                    "workflow_type": "growth",
                    "step_sequence": ["a", "b"],
                    "avg_score": 0.75,
                    "sample_count": 12,
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "ok"
            assert payload["pattern"]["pattern_id"] == "p-1"

            listed = await request(app, "GET", "/federation/patterns", params={"limit": 10})
            assert listed.status_code == 200
            listed_payload = listed.json()
            pattern_ids = {row["pattern_id"] for row in listed_payload["patterns"]}
            assert "p-1" in pattern_ids

    asyncio.run(_run())


def test_federation_consensus_returns_vote() -> None:
    async def _run() -> None:
        async with lifespan(app):
            response = await request(
                app,
                "POST",
                "/federation/consensus",
                json_body={
                    "question": "Pick one",
                    "options": ["A", "B"],
                    "requester_id": "peer-x",
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["option"] == "A"
            assert payload["reasoning"]

    asyncio.run(_run())


def test_federation_auth_required_when_secret_set() -> None:
    async def _run() -> None:
        secret = "test-fed-secret"
        url_path = "/federation/announce"
        payload = {
            "peer_id": "peer-locked",
            "address": "https://peer-locked.example.com",
            "capabilities": ["debate"],
        }
        body = json_bytes(payload)
        headers = signed_headers(secret=secret, method="POST", path=url_path, body=body)
        headers["Content-Type"] = "application/json"

        import os

        os.environ["ARCHON_FEDERATION_SHARED_SECRET"] = secret
        try:
            async with lifespan(app):
                denied = await request(app, "POST", url_path, content=body)
                assert denied.status_code == 401

                allowed = await request(app, "POST", url_path, content=body, headers=headers)
                assert allowed.status_code == 200
        finally:
            os.environ.pop("ARCHON_FEDERATION_SHARED_SECRET", None)

    asyncio.run(_run())


def test_federation_allowlist_blocks_unknown_peer(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    secret = "test-fed-secret"
    config_path = tmp_path / "archon-config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "federation:",
                "  peers:",
                "    - peer_id: peer-locked",
                "      address: https://peer-locked.example.com",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHON_CONFIG", str(config_path))
    monkeypatch.setenv("ARCHON_FEDERATION_SHARED_SECRET", secret)
    monkeypatch.setenv("ARCHON_FEDERATION_ALLOWLIST", "true")
    monkeypatch.setenv("ARCHON_FEDERATION_DB", str(tmp_path / "federation.sqlite3"))

    url_path = "/federation/announce"
    payload = {
        "peer_id": "peer-locked",
        "address": "https://peer-locked.example.com",
        "capabilities": ["debate"],
    }
    body = json_bytes(payload)
    ok_headers = signed_headers(
        secret=secret, method="POST", path=url_path, body=body, peer_id="peer-locked"
    )
    ok_headers["Content-Type"] = "application/json"

    bad_headers = signed_headers(
        secret=secret, method="POST", path=url_path, body=body, peer_id="peer-evil"
    )
    bad_headers["Content-Type"] = "application/json"

    async def _run() -> None:
        async with lifespan(app):
            ok = await request(app, "POST", url_path, content=body, headers=ok_headers)
            assert ok.status_code == 200

            denied = await request(app, "POST", url_path, content=body, headers=bad_headers)
            assert denied.status_code == 403

    asyncio.run(_run())
