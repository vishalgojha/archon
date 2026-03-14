"""Partner registration and lifecycle storage."""

from __future__ import annotations

import json
import secrets
import sqlite3
import string
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

PARTNER_TIERS = ("affiliate", "reseller", "enterprise_partner")
PARTNER_TIER_REVENUE_SHARE: dict[str, float] = {
    "affiliate": 0.10,
    "reseller": 0.25,
    "enterprise_partner": 0.40,
}
PARTNER_STATUSES = ("pending", "active", "suspended", "churned")


def _now() -> float:
    return time.time()


def _partner_id() -> str:
    return f"partner-{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class Partner:
    partner_id: str
    name: str
    email: str
    tier: str
    referral_code: str
    created_at: float = field(default_factory=_now)
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)


class PartnerRegistry:
    """SQLite-backed partner registry."""

    def __init__(self, path: str | Path = "archon_partners.sqlite3") -> None:
        self.path = Path(path)
        self._init_db()

    def register(self, name: str, email: str, tier: str) -> Partner:
        clean_name = str(name or "").strip()
        clean_email = str(email or "").strip().lower()
        clean_tier = str(tier or "").strip().lower()

        if not clean_name:
            raise ValueError("Partner name is required.")
        if not clean_email or "@" not in clean_email:
            raise ValueError("Valid partner email is required.")
        if clean_tier not in PARTNER_TIERS:
            raise ValueError(f"Invalid partner tier '{tier}'.")

        code = self._generate_unique_referral_code()
        row = Partner(
            partner_id=_partner_id(),
            name=clean_name,
            email=clean_email,
            tier=clean_tier,
            referral_code=code,
            created_at=_now(),
            status="pending",
            metadata={},
        )

        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO partners(
                        partner_id, name, email, tier, referral_code, created_at, status, metadata
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.partner_id,
                        row.name,
                        row.email,
                        row.tier,
                        row.referral_code,
                        row.created_at,
                        row.status,
                        json.dumps(row.metadata),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "partners.email" in str(exc).lower() or "email" in str(exc).lower():
                    raise ValueError(f"Partner email '{clean_email}' already exists.") from exc
                raise

        return row

    def get(self, partner_id: str) -> Partner | None:
        with self._connect() as conn:
            record = conn.execute(
                """
                SELECT partner_id, name, email, tier, referral_code, created_at, status, metadata
                FROM partners
                WHERE partner_id = ?
                """,
                (str(partner_id or "").strip(),),
            ).fetchone()
        return self._to_partner(record)

    def get_by_referral_code(self, code: str) -> Partner | None:
        with self._connect() as conn:
            record = conn.execute(
                """
                SELECT partner_id, name, email, tier, referral_code, created_at, status, metadata
                FROM partners
                WHERE referral_code = ?
                """,
                (str(code or "").strip().upper(),),
            ).fetchone()
        return self._to_partner(record)

    def list(
        self, status_filter: str | None = None, tier_filter: str | None = None
    ) -> list[Partner]:
        query = (
            "SELECT partner_id, name, email, tier, referral_code, created_at, status, metadata "
            "FROM partners"
        )
        clauses: list[str] = []
        params: list[Any] = []

        if status_filter:
            normalized_status = str(status_filter).strip().lower()
            if normalized_status not in PARTNER_STATUSES:
                raise ValueError(f"Invalid partner status '{status_filter}'.")
            clauses.append("status = ?")
            params.append(normalized_status)

        if tier_filter:
            normalized_tier = str(tier_filter).strip().lower()
            if normalized_tier not in PARTNER_TIERS:
                raise ValueError(f"Invalid partner tier '{tier_filter}'.")
            clauses.append("tier = ?")
            params.append(normalized_tier)

        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at ASC, partner_id ASC"

        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        return [self._to_partner(row) for row in rows if row is not None]

    def update_status(self, partner_id: str, status: str, reason: str) -> Partner:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in PARTNER_STATUSES:
            raise ValueError(f"Invalid partner status '{status}'.")

        target_id = str(partner_id or "").strip()
        if not target_id:
            raise ValueError("partner_id is required.")

        reason_text = str(reason or "").strip()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT metadata FROM partners WHERE partner_id = ?",
                (target_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(f"Partner '{target_id}' not found.")

            metadata = json.loads(str(existing["metadata"])) if existing["metadata"] else {}
            metadata["status_reason"] = reason_text
            metadata["status_updated_at"] = _now()

            conn.execute(
                """
                UPDATE partners
                SET status = ?, metadata = ?
                WHERE partner_id = ?
                """,
                (normalized_status, json.dumps(metadata), target_id),
            )

        updated = self.get(target_id)
        if updated is None:
            raise KeyError(f"Partner '{target_id}' not found after update.")
        return updated

    def update_metadata(self, partner_id: str, updates: dict[str, Any]) -> Partner:
        """Merge metadata fields for one partner and persist the result.

        Example:
            >>> registry = PartnerRegistry(path=":memory:")
            >>> partner = registry.register("Partner", "partner@example.com", "affiliate")
            >>> registry.update_metadata(partner.partner_id, {"region": "US"}).metadata["region"]
            'US'
        """

        target_id = str(partner_id or "").strip()
        if not target_id:
            raise ValueError("partner_id is required.")
        if not isinstance(updates, dict):
            raise ValueError("updates must be a dict.")

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT metadata FROM partners WHERE partner_id = ?",
                (target_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(f"Partner '{target_id}' not found.")

            metadata = json.loads(str(existing["metadata"])) if existing["metadata"] else {}
            metadata.update(dict(updates))
            conn.execute(
                "UPDATE partners SET metadata = ? WHERE partner_id = ?",
                (json.dumps(metadata), target_id),
            )

        updated = self.get(target_id)
        if updated is None:
            raise KeyError(f"Partner '{target_id}' not found after metadata update.")
        return updated

    def _generate_unique_referral_code(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        for _ in range(64):
            code = "".join(secrets.choice(alphabet) for _ in range(8))
            if self.get_by_referral_code(code) is None:
                return code
        raise RuntimeError("Unable to generate unique referral code after 64 attempts.")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS partners (
                    partner_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    tier TEXT NOT NULL,
                    referral_code TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_partners_status ON partners(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_partners_tier ON partners(tier)")

    @staticmethod
    def _to_partner(record: sqlite3.Row | None) -> Partner | None:
        if record is None:
            return None
        metadata = json.loads(str(record["metadata"])) if record["metadata"] else {}
        return Partner(
            partner_id=str(record["partner_id"]),
            name=str(record["name"]),
            email=str(record["email"]),
            tier=str(record["tier"]),
            referral_code=str(record["referral_code"]),
            created_at=float(record["created_at"]),
            status=str(record["status"]),
            metadata=metadata,
        )
