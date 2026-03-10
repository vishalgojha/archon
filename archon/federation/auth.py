"""Federation request signing + verification helpers.

This module provides an HMAC-based request authentication scheme for ARCHON
federation endpoints. It is intentionally simple and dependency-free.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

_HEADER_TS = "x-archon-fed-ts"
_HEADER_NONCE = "x-archon-fed-nonce"
_HEADER_SIG = "x-archon-fed-signature"
_HEADER_FROM = "x-archon-fed-from"
_SIG_PREFIX = "v1="
_SIG_PREFIX_V2 = "v2="


def json_bytes(payload: Any) -> bytes:
    """Serialize JSON deterministically for signing."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def path_with_query(url: str) -> str:
    parsed = urlparse(str(url))
    path = parsed.path or "/"
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def body_hash(body: bytes) -> str:
    return hashlib.sha256(body or b"").hexdigest()


def canonical_string(
    *,
    version: str,
    ts: int,
    nonce: str,
    method: str,
    path: str,
    body_sha256: str,
    actor: str | None = None,
) -> str:
    return "\n".join(
        [
            str(version),
            str(int(ts)),
            str(nonce),
            str(method).upper(),
            str(path),
            str(body_sha256),
            str(actor or ""),
        ]
    )


def sign(
    *,
    secret: str,
    ts: int,
    nonce: str,
    method: str,
    path: str,
    body: bytes,
) -> str:
    digest = hmac.new(
        key=str(secret).encode("utf-8"),
        msg=canonical_string(
            version="v1",
            ts=ts,
            nonce=nonce,
            method=method,
            path=path,
            body_sha256=body_hash(body),
        ).encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"{_SIG_PREFIX}{digest}"


def sign_v2(
    *,
    secret: str,
    ts: int,
    nonce: str,
    method: str,
    path: str,
    body: bytes,
    actor: str,
) -> str:
    digest = hmac.new(
        key=str(secret).encode("utf-8"),
        msg=canonical_string(
            version="v2",
            ts=ts,
            nonce=nonce,
            method=method,
            path=path,
            body_sha256=body_hash(body),
            actor=actor,
        ).encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"{_SIG_PREFIX_V2}{digest}"


def signed_headers(
    *, secret: str, method: str, path: str, body: bytes, peer_id: str | None = None
) -> dict[str, str]:
    ts = int(time.time())
    nonce = f"nonce-{uuid.uuid4().hex}"
    peer_id = str(peer_id).strip() if peer_id else None
    if peer_id:
        signature = sign_v2(
            secret=secret,
            ts=ts,
            nonce=nonce,
            method=method,
            path=path,
            body=body,
            actor=peer_id,
        )
    else:
        signature = sign(
            secret=secret,
            ts=ts,
            nonce=nonce,
            method=method,
            path=path,
            body=body,
        )
    headers = {
        "X-Archon-Fed-Ts": str(ts),
        "X-Archon-Fed-Nonce": nonce,
        "X-Archon-Fed-Signature": signature,
    }
    if peer_id:
        headers["X-Archon-Fed-From"] = peer_id
    return headers


@dataclass(slots=True)
class NonceCache:
    """Simple in-memory nonce cache with time-based pruning."""

    entries: dict[str, float]

    def prune(self, *, now: float, max_age_s: float) -> None:
        cutoff = now - max(0.0, float(max_age_s))
        stale = [nonce for nonce, created_at in self.entries.items() if float(created_at) < cutoff]
        for nonce in stale:
            self.entries.pop(nonce, None)

    def seen(self, nonce: str) -> bool:
        return str(nonce) in self.entries

    def add(self, nonce: str, *, now: float) -> None:
        self.entries[str(nonce)] = float(now)


class FederationAuthError(ValueError):
    """Raised when federation authentication fails."""


def verify(
    *,
    secret: str,
    method: str,
    path: str,
    body: bytes,
    headers: dict[str, str],
    now: float | None = None,
    max_skew_s: float = 300.0,
    nonce_cache: NonceCache | None = None,
) -> None:
    """Verify signed federation request headers and prevent replay."""

    now_value = float(time.time() if now is None else now)
    ts_raw = str(headers.get(_HEADER_TS) or headers.get("X-Archon-Fed-Ts") or "").strip()
    nonce = str(headers.get(_HEADER_NONCE) or headers.get("X-Archon-Fed-Nonce") or "").strip()
    actor = str(headers.get(_HEADER_FROM) or headers.get("X-Archon-Fed-From") or "").strip()
    provided = str(headers.get(_HEADER_SIG) or headers.get("X-Archon-Fed-Signature") or "").strip()
    if not ts_raw or not nonce or not provided:
        raise FederationAuthError("Missing federation auth headers.")
    version = None
    if provided.startswith(_SIG_PREFIX_V2):
        version = "v2"
        if not actor:
            raise FederationAuthError("Missing federation actor header.")
    elif provided.startswith(_SIG_PREFIX):
        version = "v1"
    else:
        raise FederationAuthError("Invalid federation signature prefix.")

    try:
        ts = int(ts_raw)
    except Exception as exc:  # noqa: BLE001
        raise FederationAuthError("Invalid federation timestamp.") from exc

    if abs(now_value - float(ts)) > float(max_skew_s):
        raise FederationAuthError("Federation timestamp outside allowed skew.")

    cache = nonce_cache
    if cache is not None:
        cache.prune(now=now_value, max_age_s=max_skew_s)
        if cache.seen(nonce):
            raise FederationAuthError("Federation nonce replay detected.")

    if version == "v2":
        expected = sign_v2(
            secret=secret,
            ts=ts,
            nonce=nonce,
            method=method,
            path=path,
            body=body,
            actor=actor,
        )
    else:
        expected = sign(
            secret=secret,
            ts=ts,
            nonce=nonce,
            method=method,
            path=path,
            body=body,
        )
    if not hmac.compare_digest(str(provided), str(expected)):
        raise FederationAuthError("Federation signature mismatch.")

    if cache is not None:
        cache.add(nonce, now=now_value)
