"""SQLite-backed tenant device token registry for push notifications."""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(slots=True, frozen=True)
class DeviceToken:
    token_id: str
    tenant_id: str
    platform: str
    token: str
    created_at: float


class DeviceRegistry:
    """Register/unregister and query device tokens by tenant."""

    def __init__(self, path: str | Path = "archon_device_tokens.sqlite3") -> None:
        self.path = Path(path)
        self._init_db()

    def register(self, tenant_id: str, platform: str, token: str) -> DeviceToken:
        clean_tenant = str(tenant_id or "").strip()
        clean_platform = str(platform or "").strip().lower()
        clean_token = str(token or "").strip()
        if not clean_tenant:
            raise ValueError("tenant_id is required.")
        if clean_platform not in {"android", "ios", "fcm", "apns"}:
            raise ValueError("platform must be one of: android, ios, fcm, apns.")
        if not clean_token:
            raise ValueError("token is required.")

        now = time.time()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT token_id, created_at FROM device_tokens WHERE token = ?",
                (clean_token,),
            ).fetchone()
            if existing is None:
                token_id = f"dtok-{uuid.uuid4().hex[:12]}"
                created_at = now
                conn.execute(
                    """
                    INSERT INTO device_tokens(
                        token_id, tenant_id, platform, token, created_at, last_seen, stale
                    ) VALUES (?, ?, ?, ?, ?, ?, 0)
                    """,
                    (token_id, clean_tenant, clean_platform, clean_token, created_at, now),
                )
            else:
                token_id = str(existing["token_id"])
                created_at = float(existing["created_at"])
                conn.execute(
                    """
                    UPDATE device_tokens
                    SET tenant_id = ?, platform = ?, last_seen = ?, stale = 0
                    WHERE token_id = ?
                    """,
                    (clean_tenant, clean_platform, now, token_id),
                )
        return DeviceToken(
            token_id=token_id,
            tenant_id=clean_tenant,
            platform=clean_platform,
            token=clean_token,
            created_at=created_at,
        )

    def unregister(self, token_id: str) -> bool:
        clean_token_id = str(token_id or "").strip()
        if not clean_token_id:
            return False
        with self._connect() as conn:
            result = conn.execute("DELETE FROM device_tokens WHERE token_id = ?", (clean_token_id,))
        return int(getattr(result, "rowcount", 0) or 0) > 0

    def get_by_tenant(self, tenant_id: str) -> list[DeviceToken]:
        clean_tenant = str(tenant_id or "").strip()
        if not clean_tenant:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT token_id, tenant_id, platform, token, created_at
                FROM device_tokens
                WHERE tenant_id = ? AND stale = 0
                ORDER BY created_at ASC
                """,
                (clean_tenant,),
            ).fetchall()
        return [
            DeviceToken(
                token_id=str(row["token_id"]),
                tenant_id=str(row["tenant_id"]),
                platform=str(row["platform"]),
                token=str(row["token"]),
                created_at=float(row["created_at"]),
            )
            for row in rows
        ]

    def get_tokens_for_tenant(self, tenant_id: str) -> list[DeviceToken]:
        return self.get_by_tenant(tenant_id)

    def mark_stale(self, token_id: str) -> bool:
        clean_token_id = str(token_id or "").strip()
        if not clean_token_id:
            return False
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE device_tokens SET stale = 1 WHERE token_id = ?",
                (clean_token_id,),
            )
        return int(getattr(result, "rowcount", 0) or 0) > 0

    def prune_stale(self, days: int = 90) -> int:
        threshold = time.time() - (max(1, int(days)) * 24 * 60 * 60)
        with self._connect() as conn:
            result = conn.execute(
                "DELETE FROM device_tokens WHERE last_seen < ?",
                (threshold,),
            )
        return int(getattr(result, "rowcount", 0) or 0)

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
                CREATE TABLE IF NOT EXISTS device_tokens (
                    token_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    stale INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_device_tokens_tenant ON device_tokens(tenant_id, stale, last_seen)"
            )
