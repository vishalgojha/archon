"""Stripe Connect onboarding helpers for marketplace developers."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

import httpx

from archon.compliance.encryption import EncryptionLayer
from archon.compliance.retention import RetentionRule
from archon.partners.registry import Partner, PartnerRegistry

CONNECT_ACCOUNT_RETENTION_RULE = RetentionRule(
    entity_type="marketplace_connect_account",
    retention_days=3650,
    action="archive",
)
ONBOARDING_SESSION_RETENTION_RULE = RetentionRule(
    entity_type="marketplace_onboarding_session",
    retention_days=1,
    action="delete",
)
CONNECT_ACCOUNT_METADATA_KEY = "stripe_connect_account"


def _now() -> float:
    return time.time()


def _session_id() -> str:
    return f"onboard-{uuid.uuid4().hex[:12]}"


def _default_master_key() -> bytes:
    env = str(os.getenv("ARCHON_MASTER_KEY", "")).strip()
    if env:
        try:
            return EncryptionLayer.master_key_from_env()
        except ValueError:
            pass
    return b"c" * 32


def _payload_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _flatten_form(values: dict[str, Any], *, prefix: str = "") -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        target = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            rows.update(_flatten_form(value, prefix=target))
        elif isinstance(value, bool):
            rows[target] = "true" if value else "false"
        else:
            rows[target] = value
    return rows


def _encrypt_value(partner_id: str, value: str, master_key: bytes) -> dict[str, str]:
    encrypted = EncryptionLayer.encrypt(
        str(value or ""),
        EncryptionLayer.derive_key(str(partner_id), master_key),
    )
    return asdict(encrypted)


def decrypt_partner_account_id(
    partner: Partner | None,
    *,
    master_key: bytes | None = None,
) -> str | None:
    """Decrypt the stored Stripe Connect account id from partner metadata.

    Example:
        >>> decrypt_partner_account_id(None) is None
        True
    """

    if partner is None:
        return None
    payload = partner.metadata.get(CONNECT_ACCOUNT_METADATA_KEY)
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    if not isinstance(payload, dict):
        return None
    try:
        return (
            EncryptionLayer.decrypt(
                payload,
                EncryptionLayer.derive_key(partner.partner_id, master_key or _default_master_key()),
            ).strip()
            or None
        )
    except Exception:
        return None


@dataclass(slots=True, frozen=True)
class ConnectAccount:
    """One Stripe Connect account projection."""

    account_id: str
    email: str
    country: str
    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool
    created_at: float


@dataclass(slots=True, frozen=True)
class OnboardingSession:
    """One developer onboarding redirect session."""

    session_id: str
    partner_id: str
    account_id: str
    onboarding_url: str
    expires_at: float


class StripeConnectClient:
    """Minimal Stripe Connect client using `httpx`.

    Example:
        >>> client = StripeConnectClient(secret_key="sk_test")
        >>> client.base_url
        'https://api.stripe.com/v1'
    """

    def __init__(
        self,
        secret_key: str | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.stripe.com/v1",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.secret_key = str(
            secret_key
            or os.getenv("STRIPE_SECRET_KEY")
            or os.getenv("ARCHON_STRIPE_SECRET_KEY")
            or ""
        ).strip()
        self.base_url = base_url.rstrip("/")
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        """Close the managed `httpx` client when owned by this instance."""

        if self._owns_http_client:
            await self._http.aclose()

    async def create_account(
        self,
        email: str,
        country: str,
        business_type: str,
    ) -> ConnectAccount:
        """Create one Stripe Express account."""

        payload = await self._post(
            "/accounts",
            {
                "type": "express",
                "email": str(email or "").strip(),
                "country": str(country or "").strip().upper(),
                "business_type": str(business_type or "").strip() or "individual",
            },
        )
        return _connect_account_from_payload(
            payload, fallback_email=email, fallback_country=country
        )

    async def create_account_link(
        self,
        account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> str:
        """Create one onboarding redirect URL for a Connect account."""

        payload = await self._post(
            "/account_links",
            {
                "account": str(account_id or "").strip(),
                "refresh_url": str(refresh_url or "").strip(),
                "return_url": str(return_url or "").strip(),
                "type": "account_onboarding",
            },
        )
        return str(payload.get("url") or "").strip()

    async def get_account(self, account_id: str) -> ConnectAccount:
        """Fetch one Stripe Connect account."""

        payload = await self._get(f"/accounts/{str(account_id or '').strip()}", {})
        return _connect_account_from_payload(payload)

    async def list_accounts(self, limit: int = 10) -> list[ConnectAccount]:
        """List recent Stripe Connect accounts."""

        payload = await self._get("/accounts", {"limit": max(1, min(int(limit), 100))})
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            return []
        return [_connect_account_from_payload(row) for row in rows if isinstance(row, dict)]

    async def delete_account(self, account_id: str) -> bool:
        """Delete one Stripe Connect account."""

        payload = await self._delete(f"/accounts/{str(account_id or '').strip()}")
        return bool(payload.get("deleted", False))

    async def create_transfer(
        self,
        destination_account_id: str,
        amount_usd: float,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create one payout transfer to a Connect destination account."""

        cents = int(round(max(0.0, float(amount_usd)) * 100))
        return await self._post(
            "/transfers",
            {
                "amount": cents,
                "currency": "usd",
                "destination": str(destination_account_id or "").strip(),
                "metadata": dict(metadata or {}),
            },
        )

    async def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        response = await self._http.post(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.secret_key}"},
            data=_flatten_form(data),
        )
        response.raise_for_status()
        return _payload_dict(response.json())

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await self._http.get(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.secret_key}"},
            params=params,
        )
        response.raise_for_status()
        return _payload_dict(response.json())

    async def _delete(self, path: str) -> dict[str, Any]:
        response = await self._http.delete(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.secret_key}"},
        )
        response.raise_for_status()
        return _payload_dict(response.json())


class DeveloperOnboarding:
    """Stripe Connect onboarding lifecycle for marketplace partners."""

    def __init__(
        self,
        registry: PartnerRegistry,
        *,
        stripe_client: StripeConnectClient | None = None,
        path: str | Path = "archon_marketplace_connect.sqlite3",
        refresh_url: str | None = None,
        return_url: str | None = None,
        session_ttl_seconds: int = 86400,
        master_key: bytes | None = None,
    ) -> None:
        self.registry = registry
        self.stripe_client = stripe_client or StripeConnectClient()
        self.path = Path(path)
        self.refresh_url = (
            str(refresh_url or os.getenv("ARCHON_MARKETPLACE_REFRESH_URL", "")).strip()
            or "https://archon.local/marketplace/developers/refresh"
        )
        self.return_url = (
            str(return_url or os.getenv("ARCHON_MARKETPLACE_RETURN_URL", "")).strip()
            or "https://archon.local/marketplace/developers/return"
        )
        self.session_ttl_seconds = max(60, int(session_ttl_seconds))
        self._master_key = master_key or _default_master_key()
        self._init_db()

    async def onboard(self, partner_id: str, email: str, country: str = "US") -> OnboardingSession:
        """Create a Connect account, persist it on the partner, and return an onboarding URL."""

        partner = self._partner(partner_id)
        account = await self.stripe_client.create_account(
            email=str(email or "").strip() or partner.email,
            country=country,
            business_type="individual",
        )
        self.registry.update_metadata(
            partner.partner_id,
            {
                CONNECT_ACCOUNT_METADATA_KEY: _encrypt_value(
                    partner.partner_id,
                    account.account_id,
                    self._master_key,
                ),
                "stripe_connect_account_updated_at": _now(),
            },
        )
        onboarding_url = await self.stripe_client.create_account_link(
            account.account_id,
            self.refresh_url,
            self.return_url,
        )
        session = OnboardingSession(
            session_id=_session_id(),
            partner_id=partner.partner_id,
            account_id=account.account_id,
            onboarding_url=onboarding_url,
            expires_at=_now() + float(self.session_ttl_seconds),
        )
        self._save_session(session)
        return session

    async def complete(self, partner_id: str) -> bool:
        """Mark the partner active when Stripe onboarding details are fully submitted."""

        account_id = self.get_partner_account_id(partner_id)
        if not account_id:
            return False
        account = await self.stripe_client.get_account(account_id)
        is_complete = bool(account.details_submitted and account.charges_enabled)
        if is_complete:
            self.registry.update_status(partner_id, "active", "stripe_connect_complete")
        return is_complete

    async def refresh(self, partner_id: str) -> OnboardingSession:
        """Refresh an expired onboarding session and return the active redirect session."""

        current = self.get_session(partner_id)
        if current is not None and current.expires_at > _now():
            return current
        account_id = self.get_partner_account_id(partner_id)
        if not account_id:
            raise KeyError(f"Partner '{partner_id}' has no Stripe Connect account.")
        onboarding_url = await self.stripe_client.create_account_link(
            account_id,
            self.refresh_url,
            self.return_url,
        )
        session = OnboardingSession(
            session_id=_session_id(),
            partner_id=str(partner_id or "").strip(),
            account_id=account_id,
            onboarding_url=onboarding_url,
            expires_at=_now() + float(self.session_ttl_seconds),
        )
        self._save_session(session)
        return session

    async def status(self, partner_id: str) -> tuple[ConnectAccount, bool]:
        """Return the current Stripe account projection and completion state."""

        account_id = self.get_partner_account_id(partner_id)
        if not account_id:
            raise KeyError(f"Partner '{partner_id}' has no Stripe Connect account.")
        account = await self.stripe_client.get_account(account_id)
        return account, bool(account.details_submitted and account.charges_enabled)

    def get_session(self, partner_id: str) -> OnboardingSession | None:
        """Return the latest stored onboarding session for one partner."""

        self.prune()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, partner_id, encrypted_account_json, onboarding_url, expires_at
                FROM onboarding_sessions
                WHERE partner_id = ?
                ORDER BY expires_at DESC, session_id DESC
                LIMIT 1
                """,
                (str(partner_id or "").strip(),),
            ).fetchone()
        if row is None:
            return None
        return OnboardingSession(
            session_id=str(row["session_id"]),
            partner_id=str(row["partner_id"]),
            account_id=EncryptionLayer.decrypt(
                json.loads(str(row["encrypted_account_json"])),
                EncryptionLayer.derive_key(str(row["partner_id"]), self._master_key),
            ),
            onboarding_url=str(row["onboarding_url"]),
            expires_at=float(row["expires_at"]),
        )

    def get_partner_account_id(self, partner_id: str) -> str | None:
        """Return the decrypted Stripe Connect account id stored on a partner."""

        return decrypt_partner_account_id(self._partner(partner_id), master_key=self._master_key)

    def prune(self) -> int:
        """Delete expired onboarding sessions from the local SQLite store."""

        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM onboarding_sessions WHERE expires_at < ?",
                (_now(),),
            )
        return int(cursor.rowcount)

    def _partner(self, partner_id: str) -> Partner:
        partner = self.registry.get(str(partner_id or "").strip())
        if partner is None:
            raise KeyError(f"Partner '{partner_id}' not found.")
        return partner

    def _save_session(self, session: OnboardingSession) -> None:
        encrypted = _encrypt_value(session.partner_id, session.account_id, self._master_key)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO onboarding_sessions(
                    session_id,
                    partner_id,
                    encrypted_account_json,
                    onboarding_url,
                    created_at,
                    expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.partner_id,
                    json.dumps(encrypted, separators=(",", ":")),
                    session.onboarding_url,
                    _now(),
                    session.expires_at,
                ),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS onboarding_sessions (
                    session_id TEXT PRIMARY KEY,
                    partner_id TEXT NOT NULL,
                    encrypted_account_json TEXT NOT NULL,
                    onboarding_url TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_onboarding_sessions_partner_expires ON onboarding_sessions(partner_id, expires_at)"
            )


def _connect_account_from_payload(
    payload: dict[str, Any],
    *,
    fallback_email: str = "",
    fallback_country: str = "",
) -> ConnectAccount:
    return ConnectAccount(
        account_id=str(payload.get("id") or ""),
        email=str(payload.get("email") or fallback_email or ""),
        country=str(payload.get("country") or fallback_country or ""),
        charges_enabled=bool(payload.get("charges_enabled", False)),
        payouts_enabled=bool(payload.get("payouts_enabled", False)),
        details_submitted=bool(payload.get("details_submitted", False)),
        created_at=float(payload.get("created") or _now()),
    )
