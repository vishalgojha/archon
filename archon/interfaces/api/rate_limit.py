"""Tier-aware rate limiting utilities (in-memory, Redis-ready abstraction)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from archon.interfaces.api.auth import TierName

DEFAULT_TIER_LIMITS: dict[TierName, str] = {
    "free": "30/minute",
    "pro": "120/minute",
    "enterprise": "600/minute",
}


class TierRateLimitStore(Protocol):
    """Storage interface for per-tier request limits."""

    def get_limit(self, tier: TierName) -> str:
        """Return rate-limit string for a tier (e.g., `30/minute`)."""


@dataclass(slots=True)
class InMemoryTierRateLimitStore:
    """In-memory rate-limit policy store."""

    limits: dict[TierName, str]

    @classmethod
    def from_env(cls) -> "InMemoryTierRateLimitStore":
        merged: dict[TierName, str] = dict(DEFAULT_TIER_LIMITS)
        for tier in list(merged.keys()):
            env_name = f"ARCHON_RATE_LIMIT_{tier.upper()}"
            merged[tier] = os.getenv(env_name, merged[tier])
        return cls(limits=merged)

    def get_limit(self, tier: TierName) -> str:
        return self.limits.get(tier, self.limits["free"])


@dataclass(slots=True)
class RedisReadyTierRateLimitStore:
    """Redis-ready rate-limit store contract placeholder.

    This adapter is intentionally non-operational until a Redis client is wired.
    """

    redis_url: str

    def get_limit(self, tier: TierName) -> str:
        # Fallback to default policy until Redis-backed overrides are implemented.
        return DEFAULT_TIER_LIMITS.get(tier, DEFAULT_TIER_LIMITS["free"])


_STORE: TierRateLimitStore = InMemoryTierRateLimitStore.from_env()


def set_rate_limit_store(store: TierRateLimitStore) -> None:
    """Set active tier-rate policy store used by runtime limit resolution."""

    global _STORE
    _STORE = store


def get_rate_limit_store() -> TierRateLimitStore:
    """Return active tier-rate policy store."""

    return _STORE


def create_limiter() -> Limiter:
    """Create a limiter keyed by tenant-id when authenticated."""

    def key_func(request: Request) -> str:
        auth = getattr(request.state, "auth", None)
        tier: TierName = getattr(auth, "tier", "free")
        if auth and getattr(auth, "tenant_id", None):
            return f"tier:{tier}|tenant:{auth.tenant_id}"
        return f"tier:{tier}|ip:{get_remote_address(request)}"

    return Limiter(key_func=key_func, default_limits=[])


def limit_for_key(key: str | None = None) -> str:
    """Compute dynamic limit from generated limiter key."""

    tier = "free"
    if key and key.startswith("tier:"):
        prefix, *_rest = key.split("|", 1)
        value = prefix.split(":", 1)[1].strip().lower()
        if value in DEFAULT_TIER_LIMITS:
            tier = value
    store = get_rate_limit_store()
    return store.get_limit(tier)  # type: ignore[arg-type]
