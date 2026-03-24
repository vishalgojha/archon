"""JWT authentication middleware for tenant-scoped API access."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

import jwt
from fastapi import HTTPException, Request, WebSocket
from jwt import InvalidTokenError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from archon.config import ArchonConfig, load_archon_config

TierName = Literal["free", "pro", "enterprise"]
SUPPORTED_TIERS: set[str] = {"free", "pro", "enterprise"}


@dataclass(slots=True)
class AuthContext:
    """Authenticated tenant context injected into request state."""

    tenant_id: str
    tier: TierName
    claims: dict[str, Any]


@dataclass(slots=True)
class AuthSettings:
    """JWT settings loaded from environment."""

    secret: str = "archon-dev-secret-change-me-32-bytes"
    algorithm: str = "HS256"
    issuer: str | None = None
    audience: str | None = None

    @classmethod
    def from_env(cls, config: ArchonConfig | None = None) -> "AuthSettings":
        defaults = cls()
        env_secret = str(os.getenv("ARCHON_JWT_SECRET", "")).strip()
        if not env_secret:
            if config is None:
                config_path = os.getenv("ARCHON_CONFIG", "config.archon.yaml")
                try:
                    config = load_archon_config(config_path)
                except Exception:
                    config = None
            config_secret = (
                str(getattr(getattr(config, "auth", None), "jwt_secret", "") or "").strip()
                if config is not None
                else ""
            )
        else:
            config_secret = ""
        return cls(
            secret=(env_secret or config_secret or defaults.secret),
            algorithm=(
                str(os.getenv("ARCHON_JWT_ALGORITHM", defaults.algorithm)).strip()
                or defaults.algorithm
            ),
            issuer=str(os.getenv("ARCHON_JWT_ISSUER", "")).strip() or None,
            audience=str(os.getenv("ARCHON_JWT_AUDIENCE", "")).strip() or None,
        )


class AuthMiddleware(BaseHTTPMiddleware):
    """HTTP middleware that enforces JWT bearer auth for protected routes."""

    def __init__(
        self,
        app,
        settings: AuthSettings,
        exempt_paths: set[str] | None = None,
        exempt_path_prefixes: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._settings = settings
        self._exempt_paths = exempt_paths or set()
        self._exempt_path_prefixes = exempt_path_prefixes or set()

    async def dispatch(self, request: Request, call_next):
        if _path_is_exempt(
            request.url.path,
            exempt_paths=self._exempt_paths,
            exempt_path_prefixes=self._exempt_path_prefixes,
        ):
            return await call_next(request)

        token = _extract_bearer_token(request.headers.get("Authorization"))
        if not token:
            await request.body()
            return JSONResponse(status_code=401, content={"detail": "Missing bearer token."})

        try:
            request.state.auth = decode_auth_token(token, self._resolve_settings(request))
        except HTTPException as exc:
            await request.body()
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    def _resolve_settings(self, request: Request) -> AuthSettings:
        settings = getattr(request.app.state, "auth_settings", None)
        if isinstance(settings, AuthSettings):
            return settings
        return self._settings


def decode_auth_token(token: str, settings: AuthSettings) -> AuthContext:
    """Decode and validate JWT claims into tenant auth context."""

    options: dict[str, Any] = {"require": ["sub", "tier"]}
    decode_kwargs: dict[str, Any] = {"algorithms": [settings.algorithm], "options": options}
    if settings.issuer:
        decode_kwargs["issuer"] = settings.issuer
    if settings.audience:
        decode_kwargs["audience"] = settings.audience

    try:
        claims = jwt.decode(token, settings.secret, **decode_kwargs)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc

    tier = str(claims.get("tier", "")).lower()
    if tier not in SUPPORTED_TIERS:
        raise HTTPException(status_code=403, detail=f"Unsupported tier '{tier}'.")
    tenant = str(claims["sub"]).strip()
    if not tenant:
        raise HTTPException(status_code=403, detail="Token missing subject.")

    return AuthContext(
        tenant_id=tenant,
        tier=tier,  # type: ignore[arg-type]
        claims=claims,
    )


def websocket_auth_context(websocket: WebSocket, settings: AuthSettings) -> AuthContext:
    """Authenticate WebSocket using bearer header or `token` query parameter."""

    auth_header = websocket.headers.get("authorization")
    token = _extract_bearer_token(auth_header)
    if not token:
        token = websocket.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token for websocket.")
    return decode_auth_token(token, settings)


def _extract_bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _path_is_exempt(
    path: str,
    *,
    exempt_paths: set[str],
    exempt_path_prefixes: set[str],
) -> bool:
    normalized = str(path or "").strip() or "/"
    if normalized in exempt_paths:
        return True
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in exempt_path_prefixes
    )
