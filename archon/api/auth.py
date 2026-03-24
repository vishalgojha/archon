"""Tenant JWT auth and 60-second sliding-window rate limiting."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Literal, Protocol

import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import ExpiredSignatureError, InvalidTokenError

from archon.config import load_archon_config

TierName = Literal["free", "pro", "enterprise"]
TOKEN_TYPE = "tenant"
ALGORITHM = "HS256"
TIER_RATE_LIMITS: dict[TierName, int] = {"free": 10, "pro": 100, "enterprise": 1000}
_FREE_BLOCKED_FEATURES: set[str] = set()


class TenantTokenError(ValueError):
    """Tenant token parse/validation error."""


@dataclass(slots=True)
class TenantContext:
    """Tenant-scoped context. Example: `TenantContext('t','free',10).memory_namespace`."""

    tenant_id: str
    tier: TierName
    rate_limit_per_minute: int

    @property
    def memory_namespace(self) -> str:
        """Memory namespace. Example: `TenantContext('t','pro',100).memory_namespace`."""

        return f"tenant/{self.tenant_id}/memory"

    @property
    def audit_namespace(self) -> str:
        """Audit namespace. Example: `TenantContext('t','pro',100).audit_namespace`."""

        return f"tenant/{self.tenant_id}/audit"

    @property
    def keys_namespace(self) -> str:
        """Keys namespace. Example: `TenantContext('t','pro',100).keys_namespace`."""

        return f"tenant/{self.tenant_id}/keys"

    def can_use_feature(self, feature: str) -> bool:
        """Feature gate. Example: `TenantContext('t','free',10).can_use_feature('ui_pack')`."""

        normalized = feature.strip().lower()
        if self.tier == "free" and normalized in _FREE_BLOCKED_FEATURES:
            return False
        return True


class SlidingWindowStore(Protocol):
    """Store contract for tenant request timestamps."""

    def load(self, tenant_id: str) -> list[float]:
        """Load timestamps. Example: `store.load('tenant-a') -> [1000.0]`."""

    def save(self, tenant_id: str, events: list[float]) -> None:
        """Save timestamps. Example: `store.save('tenant-a',[1000.0]) -> None`."""

    def delete(self, tenant_id: str) -> None:
        """Delete one tenant. Example: `store.delete('tenant-a') -> None`."""

    def clear(self) -> None:
        """Delete all tenants. Example: `store.clear() -> None`."""


@dataclass(slots=True)
class InMemorySlidingWindowStore:
    """In-memory timestamp store. Example: `InMemorySlidingWindowStore().load('t')`."""

    _rows: dict[str, list[float]]
    _lock: Lock

    def __init__(self) -> None:
        """Create empty store. Example: `InMemorySlidingWindowStore()`."""

        self._rows = {}
        self._lock = Lock()

    def load(self, tenant_id: str) -> list[float]:
        """Load timestamps. Example: `store.load('tenant-a') -> []`."""

        with self._lock:
            return list(self._rows.get(tenant_id, []))

    def save(self, tenant_id: str, events: list[float]) -> None:
        """Save timestamps. Example: `store.save('tenant-a',[1000.0]) -> None`."""

        with self._lock:
            self._rows[tenant_id] = list(events)

    def delete(self, tenant_id: str) -> None:
        """Delete tenant timestamps. Example: `store.delete('tenant-a') -> None`."""

        with self._lock:
            self._rows.pop(tenant_id, None)

    def clear(self) -> None:
        """Clear all timestamps. Example: `store.clear() -> None`."""

        with self._lock:
            self._rows.clear()


@dataclass(slots=True)
class RedisSlidingWindowStore:
    """Redis-ready store interface. Example: `RedisSlidingWindowStore('redis://...')`."""

    redis_url: str
    key_prefix: str = "archon:ratelimit"

    def load(self, tenant_id: str) -> list[float]:
        """Load from Redis. Example: `store.load('tenant-a') -> [...]`."""

        raise NotImplementedError("Implement Redis zset load for tenant events.")

    def save(self, tenant_id: str, events: list[float]) -> None:
        """Save to Redis. Example: `store.save('tenant-a',[1000.0]) -> None`."""

        raise NotImplementedError("Implement Redis zset save for tenant events.")

    def delete(self, tenant_id: str) -> None:
        """Delete from Redis. Example: `store.delete('tenant-a') -> None`."""

        raise NotImplementedError("Implement Redis delete for tenant events.")

    def clear(self) -> None:
        """Clear Redis data. Example: `store.clear() -> None`."""

        raise NotImplementedError("Implement Redis clear for tenant events.")


class RateLimiter:
    """60s sliding-window limiter. Example: `RateLimiter().allow('t', 1)`."""

    def __init__(
        self,
        store: SlidingWindowStore | None = None,
        *,
        window_seconds: int = 60,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """Initialize limiter. Example: `RateLimiter(window_seconds=60)`."""

        self.store = store or InMemorySlidingWindowStore()
        self.window_seconds = window_seconds
        self._clock = clock or time.time

    def allow(self, tenant_id: str, limit_per_minute: int) -> bool:
        """Record one request and return if allowed. Example: `allow('t',2) -> bool`."""

        if limit_per_minute <= 0:
            return False
        now = float(self._clock())
        window_start = now - float(self.window_seconds)
        recent = [ts for ts in self.store.load(tenant_id) if ts > window_start]
        if len(recent) >= limit_per_minute:
            self.store.save(tenant_id, recent)
            return False
        recent.append(now)
        self.store.save(tenant_id, recent)
        return True

    def reset(self, tenant_id: str | None = None) -> None:
        """Reset counters. Example: `limiter.reset('tenant-a')`."""

        if tenant_id is None:
            self.store.clear()
            return
        self.store.delete(tenant_id)


_JWT_SECRET_CACHE: str | None = None


def _jwt_secret_from_config() -> str:
    global _JWT_SECRET_CACHE
    if _JWT_SECRET_CACHE is not None:
        return _JWT_SECRET_CACHE
    config_path = os.getenv("ARCHON_CONFIG", "config.archon.yaml")
    try:
        config = load_archon_config(config_path)
    except Exception:
        _JWT_SECRET_CACHE = ""
        return _JWT_SECRET_CACHE
    secret = str(getattr(getattr(config, "auth", None), "jwt_secret", "") or "").strip()
    _JWT_SECRET_CACHE = secret
    return secret


def _jwt_secret() -> str:
    secret = os.getenv("ARCHON_JWT_SECRET", "").strip()
    if not secret:
        secret = _jwt_secret_from_config()
    if not secret:
        raise TenantTokenError("ARCHON_JWT_SECRET is not set (env or config auth.jwt_secret).")
    return secret


def create_tenant_token(
    tenant_id: str,
    tier: TierName,
    *,
    expires_in_seconds: int = 3600,
    secret: str | None = None,
    now: int | None = None,
) -> str:
    """Create HS256 tenant token. Example: `create_tenant_token('t','pro',secret='s')`."""

    if tier not in TIER_RATE_LIMITS:
        raise TenantTokenError(f"Unsupported tier '{tier}'.")
    normalized_tenant = tenant_id.strip()
    if not normalized_tenant:
        raise TenantTokenError("tenant_id is required.")
    issued_at = int(now if now is not None else time.time())
    payload = {
        "sub": normalized_tenant,
        "tier": tier,
        "iat": issued_at,
        "exp": issued_at + int(expires_in_seconds),
        "type": TOKEN_TYPE,
    }
    return jwt.encode(payload, secret or _jwt_secret(), algorithm=ALGORITHM)


def verify_tenant_token(token: str, *, secret: str | None = None) -> dict[str, Any]:
    """Verify tenant token. Example: `verify_tenant_token(token, secret='s')['type']`."""

    try:
        payload = jwt.decode(token, secret or _jwt_secret(), algorithms=[ALGORITHM])
    except ExpiredSignatureError as exc:
        raise TenantTokenError("Token expired.") from exc
    except InvalidTokenError as exc:
        raise TenantTokenError(f"Invalid token: {exc}") from exc

    token_type = str(payload.get("type", "")).strip().lower()
    if token_type != TOKEN_TYPE:
        raise TenantTokenError("Invalid token type.")

    tier = str(payload.get("tier", "")).strip().lower()
    if tier not in TIER_RATE_LIMITS:
        raise TenantTokenError(f"Unsupported tier '{tier}'.")

    tenant_id = str(payload.get("sub", "")).strip()
    if not tenant_id:
        raise TenantTokenError("Token subject is required.")
    return payload


def token_from_request(request: Request) -> str | None:
    """Read token from Bearer or `X-Archon-Key`. Example: `token_from_request(req)`."""

    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.strip().split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
            raise TenantTokenError("Invalid Authorization header format.")
        return parts[1].strip()

    header_key = request.headers.get("X-Archon-Key")
    if header_key and header_key.strip():
        return header_key.strip()
    return None


def tenant_context_from_token(token: str, *, secret: str | None = None) -> TenantContext:
    """Create `TenantContext` from token. Example: `tenant_context_from_token(token).tier`."""

    payload = verify_tenant_token(token, secret=secret)
    tier = str(payload["tier"]).lower()
    return TenantContext(
        tenant_id=str(payload["sub"]),
        tier=tier,  # type: ignore[arg-type]
        rate_limit_per_minute=TIER_RATE_LIMITS[tier],  # type: ignore[index]
    )


_RATE_LIMITER = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Get active limiter. Example: `isinstance(get_rate_limiter(), RateLimiter)`."""

    return _RATE_LIMITER


def set_rate_limiter(limiter: RateLimiter) -> None:
    """Set active limiter. Example: `set_rate_limiter(RateLimiter())`."""

    global _RATE_LIMITER
    _RATE_LIMITER = limiter


async def require_tenant(
    request: Request,
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> TenantContext:
    """Require valid tenant and rate budget. Example: `Depends(require_tenant)`."""

    try:
        token = token_from_request(request)
    except TenantTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing tenant token."
        )

    try:
        context = tenant_context_from_token(token)
    except TenantTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if not rate_limiter.allow(context.tenant_id, context.rate_limit_per_minute):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Tenant rate limit exceeded.",
        )
    request.state.tenant = context
    return context


async def optional_tenant(
    request: Request,
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> TenantContext | None:
    """Optional tenant context dependency. Example: `Depends(optional_tenant)`."""

    try:
        token = token_from_request(request)
    except TenantTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    if not token:
        return None

    try:
        context = tenant_context_from_token(token)
    except TenantTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if not rate_limiter.allow(context.tenant_id, context.rate_limit_per_minute):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Tenant rate limit exceeded.",
        )
    request.state.tenant = context
    return context
