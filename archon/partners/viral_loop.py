"""Viral partner loop utilities for embed impressions and conversions."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from archon.partners.revenue import RevenueShare


def _now() -> float:
    return time.time()


def _impression_id() -> str:
    return f"imp-{uuid.uuid4().hex[:12]}"


def _conversion_id() -> str:
    return f"conv-{uuid.uuid4().hex[:12]}"


def visitor_fingerprint(ip: str, user_agent: str, day: date | str | None = None) -> str:
    """Hash `(ip + user_agent + date)` into a non-PII visitor fingerprint."""

    if day is None:
        day_text = date.today().isoformat()
    elif isinstance(day, date):
        day_text = day.isoformat()
    else:
        day_text = str(day)
    raw = f"{str(ip)}|{str(user_agent)}|{day_text}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


@dataclass(slots=True)
class EmbedImpression:
    impression_id: str
    partner_id: str
    site_url: str
    visitor_fingerprint: str
    timestamp: float = field(default_factory=_now)


@dataclass(slots=True)
class EmbedConversion:
    conversion_id: str
    impression_id: str
    partner_id: str
    customer_id: str
    timestamp: float = field(default_factory=_now)


@dataclass(slots=True)
class Funnel:
    impressions: int
    conversions: int
    conversion_rate: float
    attributed_revenue: float


class ViralLoop:
    """Track partner embed traffic and attribution-window conversions."""

    def __init__(
        self,
        path: str | Path = "archon_partner_viral.sqlite3",
        *,
        attribution_window_hours: int = 72,
        revenue_share: RevenueShare | None = None,
    ) -> None:
        self.path = Path(path)
        self.attribution_window_hours = int(attribution_window_hours)
        self.revenue_share = revenue_share
        self._init_db()

    def record_impression(
        self,
        partner_id: str,
        site_url: str,
        visitor_fingerprint: str,
    ) -> EmbedImpression:
        clean_partner = str(partner_id or "").strip()
        clean_site = str(site_url or "").strip()
        clean_fingerprint = self._normalize_fingerprint(visitor_fingerprint)

        if not clean_partner:
            raise ValueError("partner_id is required.")
        if not clean_site:
            raise ValueError("site_url is required.")

        row = EmbedImpression(
            impression_id=_impression_id(),
            partner_id=clean_partner,
            site_url=clean_site,
            visitor_fingerprint=clean_fingerprint,
            timestamp=_now(),
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO impressions(impression_id, partner_id, site_url, visitor_fingerprint, timestamp)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    row.impression_id,
                    row.partner_id,
                    row.site_url,
                    row.visitor_fingerprint,
                    row.timestamp,
                ),
            )

        return row

    def record_conversion(self, impression_id: str, customer_id: str) -> EmbedConversion:
        clean_impression = str(impression_id or "").strip()
        clean_customer = str(customer_id or "").strip()
        if not clean_impression:
            raise ValueError("impression_id is required.")
        if not clean_customer:
            raise ValueError("customer_id is required.")

        with self._connect() as conn:
            impression = conn.execute(
                """
                SELECT impression_id, partner_id, timestamp
                FROM impressions
                WHERE impression_id = ?
                """,
                (clean_impression,),
            ).fetchone()
            if impression is None:
                raise KeyError(f"Impression '{clean_impression}' not found.")

            now = _now()
            age_seconds = now - float(impression["timestamp"])
            counted = 1 if age_seconds <= self.attribution_window_hours * 3600 else 0

            row = EmbedConversion(
                conversion_id=_conversion_id(),
                impression_id=str(impression["impression_id"]),
                partner_id=str(impression["partner_id"]),
                customer_id=clean_customer,
                timestamp=now,
            )

            conn.execute(
                """
                INSERT INTO conversions(
                    conversion_id, impression_id, partner_id, customer_id, timestamp, counted
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    row.conversion_id,
                    row.impression_id,
                    row.partner_id,
                    row.customer_id,
                    row.timestamp,
                    counted,
                ),
            )

        return row

    def get_funnel(self, partner_id: str) -> Funnel:
        clean_partner = str(partner_id or "").strip()
        if not clean_partner:
            raise ValueError("partner_id is required.")

        with self._connect() as conn:
            impression_row = conn.execute(
                "SELECT COUNT(*) AS count FROM impressions WHERE partner_id = ?",
                (clean_partner,),
            ).fetchone()
            conversion_row = conn.execute(
                "SELECT COUNT(*) AS count FROM conversions WHERE partner_id = ? AND counted = 1",
                (clean_partner,),
            ).fetchone()
            customer_rows = conn.execute(
                "SELECT DISTINCT customer_id FROM conversions WHERE partner_id = ? AND counted = 1",
                (clean_partner,),
            ).fetchall()

        impressions = int(impression_row["count"] if impression_row else 0)
        conversions = int(conversion_row["count"] if conversion_row else 0)
        conversion_rate = (conversions / impressions) if impressions else 0.0

        attributed_revenue = 0.0
        if self.revenue_share is not None and customer_rows:
            attributed_revenue = self.revenue_share.get_revenue_for_customers(
                [str(row["customer_id"]) for row in customer_rows]
            )

        return Funnel(
            impressions=impressions,
            conversions=conversions,
            conversion_rate=round(conversion_rate, 6),
            attributed_revenue=round(float(attributed_revenue), 2),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS impressions (
                    impression_id TEXT PRIMARY KEY,
                    partner_id TEXT NOT NULL,
                    site_url TEXT NOT NULL,
                    visitor_fingerprint TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversions (
                    conversion_id TEXT PRIMARY KEY,
                    impression_id TEXT NOT NULL,
                    partner_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    counted INTEGER NOT NULL,
                    FOREIGN KEY (impression_id) REFERENCES impressions(impression_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_impressions_partner ON impressions(partner_id, timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversions_partner ON conversions(partner_id, counted, timestamp)")

    @staticmethod
    def _normalize_fingerprint(raw: str) -> str:
        value = str(raw or "").strip()
        if re.fullmatch(r"[0-9a-f]{64}", value.lower()):
            return value.lower()
        return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()
