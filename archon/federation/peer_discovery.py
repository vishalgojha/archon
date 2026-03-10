"""Peer discovery and announce flow for ARCHON federation."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from archon.federation.auth import json_bytes, path_with_query, signed_headers


@dataclass(slots=True, frozen=True)
class Peer:
    """Federated ARCHON peer descriptor."""

    peer_id: str
    address: str
    public_key: str
    last_seen: float
    capabilities: list[str]
    version: str


class PeerRegistry:
    """Async peer registry with address validation and announce broadcast."""

    def __init__(
        self,
        *,
        production_mode: bool = False,
        timeout_seconds: float = 5.0,
        store: Any | None = None,
    ) -> None:
        self.production_mode = production_mode
        self._peers: dict[str, Peer] = {}
        self._client = httpx.AsyncClient(timeout=timeout_seconds)
        self._store = store
        if self._store is not None:
            try:
                for peer in list(self._store.list_peers()):
                    self._peers[peer.peer_id] = peer
            except Exception:
                self._peers = {}

    async def aclose(self) -> None:
        """Close outbound HTTP client resources."""

        await self._client.aclose()

    async def register(self, peer: Peer) -> Peer:
        """Register peer and broadcast announce to currently known peers."""

        normalized_address = _validate_address(peer.address, production_mode=self.production_mode)
        normalized = Peer(
            peer_id=peer.peer_id,
            address=normalized_address,
            public_key=peer.public_key,
            last_seen=float(peer.last_seen),
            capabilities=[str(item) for item in peer.capabilities],
            version=peer.version,
        )
        self._peers[normalized.peer_id] = normalized
        if self._store is not None:
            try:
                self._store.upsert_peer(normalized)
            except Exception:
                pass
        await self.announce(normalized.address, normalized.capabilities)
        return normalized

    async def upsert_inbound(self, peer: Peer) -> Peer:
        """Upsert an inbound peer entry without rebroadcasting announce.

        This is intended for handling `/federation/announce` payloads received from
        other peers; rebroadcasting an announce in response can create feedback loops.
        """

        normalized_address = _validate_address(peer.address, production_mode=self.production_mode)
        normalized = Peer(
            peer_id=peer.peer_id,
            address=normalized_address,
            public_key=peer.public_key,
            last_seen=float(peer.last_seen),
            capabilities=[str(item) for item in peer.capabilities],
            version=peer.version,
        )
        existing = self._peers.get(normalized.peer_id)
        if existing is not None:
            normalized = Peer(
                peer_id=normalized.peer_id,
                address=normalized.address or existing.address,
                public_key=normalized.public_key or existing.public_key,
                last_seen=max(float(existing.last_seen), float(normalized.last_seen)),
                capabilities=list(normalized.capabilities or existing.capabilities),
                version=normalized.version or existing.version,
            )
        self._peers[normalized.peer_id] = normalized
        if self._store is not None:
            try:
                self._store.upsert_peer(normalized)
            except Exception:
                pass
        return normalized

    async def announce(self, address: str, capabilities: list[str]) -> None:
        """Send announce payload to `/federation/announce` for all known peers."""

        source_address = _validate_address(address, production_mode=self.production_mode)
        payload = {
            "address": source_address,
            "capabilities": [str(item) for item in capabilities],
            "timestamp": time.time(),
        }
        tasks = []
        for peer in self._peers.values():
            if peer.address == source_address:
                continue
            target = f"{peer.address.rstrip('/')}/federation/announce"
            tasks.append(asyncio.create_task(self._post_json(target, payload)))
        if tasks:
            await asyncio.gather(*tasks)

    async def heartbeat(self, peer_id: str) -> None:
        """Update target peer heartbeat and remove peers stale for >10 minutes."""

        now = time.time()
        peer = self._peers.get(peer_id)
        if peer is not None:
            self._peers[peer_id] = Peer(
                peer_id=peer.peer_id,
                address=peer.address,
                public_key=peer.public_key,
                last_seen=now,
                capabilities=list(peer.capabilities),
                version=peer.version,
            )

        stale_cutoff = now - 600.0
        stale_ids = [pid for pid, row in self._peers.items() if row.last_seen < stale_cutoff]
        for stale_id in stale_ids:
            self._peers.pop(stale_id, None)
        if self._store is not None:
            try:
                for peer in self._peers.values():
                    self._store.upsert_peer(peer)
            except Exception:
                pass

    async def discover(self, capability_filter: str | None = None) -> list[Peer]:
        """Discover peers optionally filtered by capability."""

        peers = list(self._peers.values())
        if not capability_filter:
            return peers
        capability = str(capability_filter)
        return [peer for peer in peers if capability in peer.capabilities]

    async def _post_json(self, url: str, payload: dict[str, Any]) -> None:
        try:
            secret = str(os.getenv("ARCHON_FEDERATION_SHARED_SECRET", "")).strip()
            if secret:
                body = json_bytes(payload)
                actor = (
                    str(os.getenv("ARCHON_INSTANCE_ID", "local-instance")).strip()
                    or "local-instance"
                )
                headers = signed_headers(
                    secret=secret,
                    method="POST",
                    path=path_with_query(url),
                    body=body,
                    peer_id=actor,
                )
                headers["Content-Type"] = "application/json"
                await self._client.post(url, content=body, headers=headers)
            else:
                await self._client.post(url, json=payload)
        except Exception:
            return


def _validate_address(address: str, *, production_mode: bool) -> str:
    parsed = urlparse(str(address).strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Peer address must be http/https URL: {address}")
    if not parsed.netloc:
        raise ValueError(f"Peer address missing host: {address}")

    host = (parsed.hostname or "").lower()
    if production_mode and host in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Localhost peer addresses are not allowed in production mode.")
    return parsed.geturl().rstrip("/")
