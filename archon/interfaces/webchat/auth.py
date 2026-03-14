"""Webchat token issuance and verification utilities."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from archon.api.auth import TIER_RATE_LIMITS, TenantContext
from archon.config import load_archon_config

ALGORITHM = "HS256"
TOKEN_TYPE = "webchat"
ANON_TOKEN_TTL_SECONDS = 72 * 3600
IDENTIFIED_TOKEN_TTL_SECONDS = 24 * 3600
_TIER_ALIAS: dict[str, str] = {
    "free": "free",
    "pro": "pro",
    "enterprise": "enterprise",
    "growth": "pro",
    "business": "enterprise",
}

_JWT_SECRET_CACHE: str | None = None


class WebChatTokenError(ValueError):
    """Raised when a webchat token cannot be verified."""


@dataclass(slots=True)
class WebChatIdentity:
    """Verified webchat identity with attached token.

    Example:
        >>> identity = WebChatIdentity("t", "tenant-a", "free", "s1", 1, 2, False)
        >>> identity.session_id
        's1'
    """

    token: str
    tenant_id: str
    tier: str
    session_id: str
    issued_at: int
    expires_at: int
    is_anonymous: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize identity for API responses.

        Example:
            >>> WebChatIdentity("t", "tenant-a", "free", "s1", 1, 2, False).to_dict()["tier"]
            'free'
        """

        return {
            "token": self.token,
            "tenant_id": self.tenant_id,
            "tier": self.tier,
            "session_id": self.session_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "is_anonymous": self.is_anonymous,
        }


def create_anonymous_token(
    session_id: str,
    *,
    now: int | None = None,
    expires_in_seconds: int = ANON_TOKEN_TTL_SECONDS,
    secret: str | None = None,
) -> WebChatIdentity:
    """Create a 72-hour anonymous webchat token.

    Example:
        >>> token = create_anonymous_token("session-1", secret="secret")
        >>> token.tenant_id.startswith("anon:")
        True
    """

    tenant_id = f"anon:{uuid.uuid4().hex[:12]}"
    return _create_identity_token(
        tenant_id=tenant_id,
        tier="free",
        session_id=session_id,
        is_anonymous=True,
        now=now,
        expires_in_seconds=expires_in_seconds,
        secret=secret,
    )


def create_identified_token(
    tenant_id: str,
    tier: str,
    session_id: str,
    *,
    now: int | None = None,
    expires_in_seconds: int = IDENTIFIED_TOKEN_TTL_SECONDS,
    secret: str | None = None,
) -> WebChatIdentity:
    """Create an identified webchat token for one tenant/tier.

    Example:
        >>> token = create_identified_token("tenant-1", "pro", "session-1", secret="secret")
        >>> token.is_anonymous
        False
    """

    normalized_tenant = tenant_id.strip()
    if not normalized_tenant:
        raise WebChatTokenError("tenant_id is required.")
    normalized_tier = tier.strip().lower()
    if normalized_tier not in _TIER_ALIAS:
        raise WebChatTokenError(f"Unsupported tier '{tier}'.")
    return _create_identity_token(
        tenant_id=normalized_tenant,
        tier=normalized_tier,
        session_id=session_id,
        is_anonymous=False,
        now=now,
        expires_in_seconds=expires_in_seconds,
        secret=secret,
    )


def verify_webchat_token(token: str, *, secret: str | None = None) -> WebChatIdentity:
    """Decode and validate one webchat token.

    Example:
        >>> issued = create_identified_token("tenant-1", "pro", "s1", secret="secret")
        >>> verify_webchat_token(issued.token, secret="secret").tenant_id
        'tenant-1'
    """

    try:
        payload = jwt.decode(token, secret or _jwt_secret(), algorithms=[ALGORITHM])
    except ExpiredSignatureError as exc:
        raise WebChatTokenError("Webchat token expired.") from exc
    except InvalidTokenError as exc:
        raise WebChatTokenError(f"Invalid webchat token: {exc}") from exc

    token_type = str(payload.get("type", "")).strip().lower()
    if token_type != TOKEN_TYPE:
        raise WebChatTokenError("Invalid webchat token type.")

    tenant_id = str(payload.get("sub", "")).strip()
    if not tenant_id:
        raise WebChatTokenError("Token subject is required.")

    session_id = str(payload.get("sid", "")).strip()
    if not session_id:
        raise WebChatTokenError("Session id claim is required.")

    tier = str(payload.get("tier", "")).strip().lower()
    if tier not in _TIER_ALIAS:
        raise WebChatTokenError(f"Unsupported tier '{tier}'.")

    issued_at = int(payload.get("iat") or 0)
    expires_at = int(payload.get("exp") or 0)
    is_anonymous = bool(payload.get("anon", tenant_id.startswith("anon:")))
    return WebChatIdentity(
        token=token,
        tenant_id=tenant_id,
        tier=tier,
        session_id=session_id,
        issued_at=issued_at,
        expires_at=expires_at,
        is_anonymous=is_anonymous,
    )


def identity_to_tenant_context(identity: WebChatIdentity) -> TenantContext:
    """Convert a webchat identity into API tenant context.

    Example:
        >>> ctx = identity_to_tenant_context(WebChatIdentity("t","tenant-1","growth","s1",1,2,False))
        >>> ctx.tier
        'pro'
    """

    mapped_tier = _TIER_ALIAS.get(identity.tier)
    if mapped_tier is None:
        raise WebChatTokenError(f"Unsupported tier '{identity.tier}'.")
    if mapped_tier not in TIER_RATE_LIMITS:
        raise WebChatTokenError(f"Unsupported mapped tier '{mapped_tier}'.")
    return TenantContext(
        tenant_id=identity.tenant_id,
        tier=mapped_tier,  # type: ignore[arg-type]
        rate_limit_per_minute=TIER_RATE_LIMITS[mapped_tier],  # type: ignore[index]
    )


def _jwt_secret() -> str:
    secret = os.getenv("ARCHON_JWT_SECRET", "").strip()
    if not secret:
        global _JWT_SECRET_CACHE
        if _JWT_SECRET_CACHE is None:
            config_path = os.getenv("ARCHON_CONFIG", "config.archon.yaml")
            try:
                config = load_archon_config(config_path)
            except Exception:
                _JWT_SECRET_CACHE = ""
            else:
                _JWT_SECRET_CACHE = str(
                    getattr(getattr(config, "auth", None), "jwt_secret", "") or ""
                ).strip()
        secret = _JWT_SECRET_CACHE or ""
    if not secret:
        raise WebChatTokenError("ARCHON_JWT_SECRET is not set (env or config auth.jwt_secret).")
    return secret


def _create_identity_token(
    *,
    tenant_id: str,
    tier: str,
    session_id: str,
    is_anonymous: bool,
    now: int | None,
    expires_in_seconds: int,
    secret: str | None,
) -> WebChatIdentity:
    normalized_session = session_id.strip()
    if not normalized_session:
        raise WebChatTokenError("session_id is required.")
    if expires_in_seconds <= 0:
        raise WebChatTokenError("expires_in_seconds must be > 0.")
    issued_at = int(now if now is not None else time.time())
    expires_at = issued_at + int(expires_in_seconds)
    payload = {
        "sub": tenant_id,
        "tier": tier,
        "sid": normalized_session,
        "iat": issued_at,
        "exp": expires_at,
        "type": TOKEN_TYPE,
        "anon": bool(is_anonymous),
    }
    token = jwt.encode(payload, secret or _jwt_secret(), algorithm=ALGORITHM)
    return WebChatIdentity(
        token=token,
        tenant_id=tenant_id,
        tier=tier,
        session_id=normalized_session,
        issued_at=issued_at,
        expires_at=expires_at,
        is_anonymous=bool(is_anonymous),
    )
