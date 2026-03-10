from __future__ import annotations

import asyncio
import os
from typing import Any

import click
import httpx

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand
from archon.cli.copy import DRAWER_COPY
from archon.federation.auth import json_bytes, path_with_query, signed_headers

DRAWER_ID = "federation"
COMMAND_IDS = ("federation.peers", "federation.sync")
DRAWER_META = DRAWER_COPY[DRAWER_ID]
COMMAND_HELP = DRAWER_META["commands"]

DEFAULT_SERVER_URL = "http://127.0.0.1:8000"


def _federation_secret() -> str:
    return str(os.getenv("ARCHON_FEDERATION_SHARED_SECRET", "")).strip()


def _signed_headers_for(url: str, *, method: str, body: bytes) -> dict[str, str] | None:
    secret = _federation_secret()
    if not secret:
        return None
    actor = str(os.getenv("ARCHON_INSTANCE_ID", "local-instance")).strip() or "local-instance"
    return signed_headers(
        secret=secret,
        method=method,
        path=path_with_query(url),
        body=body,
        peer_id=actor,
    )


def _server_url_from_bindings(bindings: Any) -> str:
    return str(getattr(bindings, "DEFAULT_SERVER_URL", "") or DEFAULT_SERVER_URL).rstrip("/")


def _config_peers(config: Any) -> list[dict[str, Any]]:
    federation = getattr(config, "federation", None)
    peers = getattr(federation, "peers", None) if federation is not None else None
    if peers is None:
        extra = getattr(config, "model_extra", None)
        if not isinstance(extra, dict):
            extra = getattr(config, "__pydantic_extra__", {}) or {}
        federation = extra.get("federation", {}) if isinstance(extra, dict) else {}
        if not isinstance(federation, dict):
            return []
        peers = federation.get("peers", [])
        if not isinstance(peers, list):
            return []
    normalized: list[dict[str, Any]] = []
    for row in peers:
        if isinstance(row, str) and row.strip():
            normalized.append({"address": row.strip(), "capabilities": []})
            continue
        if hasattr(row, "address"):
            normalized.append(
                {
                    "peer_id": getattr(row, "peer_id", None),
                    "address": str(getattr(row, "address", "")).strip(),
                    "capabilities": list(getattr(row, "capabilities", []) or []),
                    "version": getattr(row, "version", None),
                    "public_key": getattr(row, "public_key", None),
                }
            )
            continue
        if isinstance(row, dict) and row.get("address"):
            normalized.append(
                {
                    "peer_id": row.get("peer_id"),
                    "address": str(row.get("address", "")).strip(),
                    "capabilities": list(row.get("capabilities") or []),
                    "version": row.get("version"),
                    "public_key": row.get("public_key"),
                }
            )
    return [peer for peer in normalized if peer.get("address")]


class _Peers(ArchonCommand):
    command_id = COMMAND_IDS[0]

    async def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        source: str,
        server_url: str,
        config_path: str,
    ):
        show_config = source in {"config", "both"}
        show_server = source in {"server", "both"}
        config = session.run_step(0, self.bindings._load_config, config_path)
        config_peers = (
            session.run_step(1, _config_peers, config)
            if show_config
            else session.run_step(1, lambda: [])
        )
        server_peers: list[dict[str, Any]] = []

        async def _fetch_server_peers() -> list[dict[str, Any]]:
            url = f"{server_url.rstrip('/')}/federation/peers"
            headers = _signed_headers_for(url, method="GET", body=b"")
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
            peers = payload.get("peers", [])
            return peers if isinstance(peers, list) else []

        if show_server:
            try:
                server_peers = await session.run_step_async(2, _fetch_server_peers)
            except Exception:
                server_peers = []
        else:
            session.run_step(2, lambda: None)

        lines: list[str] = []
        if show_config:
            for peer in config_peers:
                capabilities = ",".join(str(item) for item in (peer.get("capabilities") or []))
                lines.append(
                    f"config  {peer.get('peer_id') or '-':<14} {peer['address']} {capabilities}"
                )
        if show_server:
            for peer in server_peers:
                capabilities = ",".join(str(item) for item in (peer.get("capabilities") or []))
                lines.append(
                    f"server  {str(peer.get('peer_id', '-')):<14} {str(peer.get('address', ''))} {capabilities}"
                )

        session.run_step(3, lambda: None)
        if lines:
            session.print(renderer.detail_panel(self.command_id, lines))
        return {
            "configured_peers": len(config_peers),
            "runtime_peers": len(server_peers),
        }


class _Sync(ArchonCommand):
    command_id = COMMAND_IDS[1]

    async def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        server_url: str,
        self_address: str | None,
        announce: bool,
        patterns: bool,
        pull: bool,
        pattern_limit: int,
        config_path: str,
    ):
        config = session.run_step(0, self.bindings._load_config, config_path)
        peers = session.run_step(1, _config_peers, config)
        if not peers:
            raise click.ClickException(
                "No federation peers configured in config (federation.peers)."
            )

        instance_id = str(os.getenv("ARCHON_INSTANCE_ID", "local-instance"))
        version = str(getattr(self.bindings, "_resolve_version", lambda: "unknown")())
        address = (self_address or server_url).rstrip("/")
        payload = {
            "peer_id": instance_id,
            "address": address,
            "timestamp": None,
            "capabilities": ["debate", "growth"],
            "version": version,
            "public_key": "unknown",
        }

        targets = [
            str(peer.get("address", "")).rstrip("/") for peer in peers if peer.get("address")
        ]
        targets = sorted(set(targets))

        async def _post_announce() -> int:
            if not announce:
                return 0
            async with httpx.AsyncClient(timeout=5.0) as client:
                body = json_bytes(payload)
                jobs = []
                for target in targets:
                    url = f"{target}/federation/announce"
                    headers = _signed_headers_for(url, method="POST", body=body) or {}
                    headers["Content-Type"] = "application/json"
                    if _federation_secret():
                        jobs.append(client.post(url, content=body, headers=headers))
                    else:
                        jobs.append(client.post(url, json=payload))
                results = await asyncio.gather(*jobs, return_exceptions=True)
            return sum(
                1
                for response in results
                if isinstance(response, httpx.Response) and response.status_code < 400
            )

        async def _push_patterns() -> int:
            if not patterns:
                return 0
            async with httpx.AsyncClient(timeout=10.0) as client:
                local_url = (
                    f"{server_url.rstrip('/')}/federation/patterns?limit={int(pattern_limit)}"
                )
                local_headers = _signed_headers_for(local_url, method="GET", body=b"")
                local = await client.get(local_url, headers=local_headers)
                if local.status_code >= 400:
                    return 0
                local_payload = local.json()
                items = local_payload.get("patterns", [])
                if not isinstance(items, list) or not items:
                    return 0
                sent = 0
                for item in items:
                    body = json_bytes(item)
                    for target in targets:
                        url = f"{target}/federation/patterns"
                        headers = _signed_headers_for(url, method="POST", body=body) or {}
                        headers["Content-Type"] = "application/json"
                        if _federation_secret():
                            response = await client.post(url, content=body, headers=headers)
                        else:
                            response = await client.post(url, json=item)
                        if response.status_code < 400:
                            sent += 1
                return sent

        async def _pull_patterns() -> int:
            if not pull:
                return 0
            received = 0
            async with httpx.AsyncClient(timeout=10.0) as client:
                for target in targets:
                    remote_url = f"{target}/federation/patterns?limit={int(pattern_limit)}"
                    remote_headers = _signed_headers_for(remote_url, method="GET", body=b"")
                    response = await client.get(remote_url, headers=remote_headers)
                    if response.status_code >= 400:
                        continue
                    payload = response.json()
                    items = payload.get("patterns", [])
                    if not isinstance(items, list) or not items:
                        continue
                    for item in items:
                        local_post_url = f"{server_url.rstrip('/')}/federation/patterns"
                        body = json_bytes(item)
                        headers = (
                            _signed_headers_for(local_post_url, method="POST", body=body) or {}
                        )
                        headers["Content-Type"] = "application/json"
                        stored = await client.post(local_post_url, content=body, headers=headers)
                        if stored.status_code < 400:
                            received += 1
            return received

        announce_count = 0
        if announce:
            announce_count = await session.run_step_async(2, _post_announce)
        else:
            session.run_step(2, lambda: None)

        pattern_pushes = await session.run_step_async(3, _push_patterns)
        pattern_pulls = await session.run_step_async(4, _pull_patterns)
        lines = [
            f"targets={len(targets)}",
            f"announce_ok={announce_count}",
            f"pattern_pushes_ok={pattern_pushes}",
            f"pattern_pulls_ok={pattern_pulls}",
        ]
        session.print(renderer.detail_panel(self.command_id, lines))
        return {
            "target_count": len(targets),
            "announce_ok": announce_count,
            "pattern_pushes_ok": pattern_pushes,
            "pattern_pulls_ok": pattern_pulls,
        }


def build_group(bindings):
    @click.group(
        name=DRAWER_ID,
        invoke_without_command=True,
        help=str(DRAWER_META["tagline"]),
    )
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("peers", help=str(COMMAND_HELP[COMMAND_IDS[0]]))
    @click.option(
        "--source",
        type=click.Choice(["both", "config", "server"], case_sensitive=False),
        default="both",
        show_default=True,
    )
    @click.option("--server-url", default=_server_url_from_bindings(bindings), show_default=True)
    @click.option("--config", "config_path", default="config.archon.yaml", show_default=True)
    def peers_command(source: str, server_url: str, config_path: str) -> None:
        _Peers(bindings).invoke(
            source=source.lower(), server_url=server_url, config_path=config_path
        )

    @group.command("sync", help=str(COMMAND_HELP[COMMAND_IDS[1]]))
    @click.option("--server-url", default=_server_url_from_bindings(bindings), show_default=True)
    @click.option("--self-address", default=None)
    @click.option("--announce/--no-announce", default=True, show_default=True)
    @click.option("--patterns/--no-patterns", default=True, show_default=True)
    @click.option("--pull/--no-pull", default=True, show_default=True)
    @click.option("--pattern-limit", default=25, show_default=True, type=int)
    @click.option("--config", "config_path", default="config.archon.yaml", show_default=True)
    def sync_command(
        server_url: str,
        self_address: str | None,
        announce: bool,
        patterns: bool,
        pull: bool,
        pattern_limit: int,
        config_path: str,
    ) -> None:
        _Sync(bindings).invoke(
            server_url=server_url,
            self_address=self_address,
            announce=announce,
            patterns=patterns,
            pull=pull,
            pattern_limit=pattern_limit,
            config_path=config_path,
        )

    return group
