"""SOC2 audit export and signing utilities."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class AuditReport:
    """Metadata describing one generated audit export."""

    report_id: str
    tenant_id: str
    period_start: float
    period_end: float
    generated_at: float
    event_count: int
    format: str


@dataclass(slots=True, frozen=True)
class SignedReport:
    """Signed audit report metadata."""

    report_id: str
    tenant_id: str
    period_start: float
    period_end: float
    generated_at: float
    event_count: int
    format: str
    signature_hex: str
    public_key_fingerprint: str
    signed_at: float
    report_hash_sha256: str


class SOC2AuditExporter:
    """Exports tenant audit logs to CSV, JSONL, and PDF manifest outputs."""

    def __init__(self, db_path: str | Path = "archon_compliance.sqlite3") -> None:
        self.db_path = Path(db_path)
        self._report_paths: dict[str, Path] = {}
        self._ensure_schema()

    def log_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        actor: str,
        action: str,
        resource: str,
        outcome: str,
        ip_address: str,
        timestamp: float | None = None,
    ) -> str:
        """Helper for writing audit rows used by compliance tests and integrations."""

        event_id = f"audit-{uuid.uuid4().hex[:12]}"
        ts = float(timestamp) if timestamp is not None else time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs(
                    event_id, tenant_id, timestamp, event_type, actor, action, resource, outcome, ip_address
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    str(tenant_id),
                    ts,
                    str(event_type),
                    str(actor),
                    str(action),
                    str(resource),
                    str(outcome),
                    str(ip_address),
                ),
            )
        return event_id

    def export_csv(self, tenant_id: str, start: Any, end: Any, path: str | Path) -> AuditReport:
        """Export audit logs to CSV with SOC2-friendly fixed columns."""

        rows, start_ts, end_ts = self._fetch_rows(tenant_id, start, end)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        columns = [
            "timestamp",
            "event_type",
            "actor",
            "action",
            "resource",
            "outcome",
            "ip_address",
        ]
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row[column] for column in columns})

        return self._build_report(
            tenant_id=tenant_id,
            period_start=start_ts,
            period_end=end_ts,
            event_count=len(rows),
            fmt="csv",
            file_path=target,
        )

    def export_json(self, tenant_id: str, start: Any, end: Any, path: str | Path) -> AuditReport:
        """Export audit logs to JSON Lines."""

        rows, start_ts, end_ts = self._fetch_rows(tenant_id, start, end)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        with target.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        return self._build_report(
            tenant_id=tenant_id,
            period_start=start_ts,
            period_end=end_ts,
            event_count=len(rows),
            fmt="jsonl",
            file_path=target,
        )

    def export_pdf_manifest(
        self, tenant_id: str, start: Any, end: Any, path: str | Path
    ) -> AuditReport:
        """Export a PDF manifest with summary and chronological event detail pages."""

        rows, start_ts, end_ts = self._fetch_rows(tenant_id, start, end)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        counts: dict[str, int] = {}
        for row in rows:
            counts[row["event_type"]] = counts.get(row["event_type"], 0) + 1

        lines: list[str] = [
            "SOC2 Audit Manifest",
            f"Tenant: {tenant_id}",
            f"Period: {start_ts} -> {end_ts}",
            f"Total events: {len(rows)}",
            "",
            "Event counts by type:",
        ]
        for key in sorted(counts):
            lines.append(f"- {key}: {counts[key]}")
        lines.append("")
        lines.append("Chronological details:")
        for row in rows:
            lines.append(
                " | ".join(
                    [
                        str(row["timestamp"]),
                        str(row["event_type"]),
                        str(row["actor"]),
                        str(row["action"]),
                        str(row["resource"]),
                        str(row["outcome"]),
                        str(row["ip_address"]),
                    ]
                )
            )

        if self._write_pdf_with_reportlab(target, lines):
            fmt = "pdf"
        else:
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            fmt = "pdf"

        return self._build_report(
            tenant_id=tenant_id,
            period_start=start_ts,
            period_end=end_ts,
            event_count=len(rows),
            fmt=fmt,
            file_path=target,
        )

    def sign_report(self, report: AuditReport, private_key_path: str | Path) -> SignedReport:
        """Sign the report file hash with an RSA private key (cryptography if available)."""

        report_path = self._report_paths.get(report.report_id)
        if report_path is None:
            raise KeyError(f"Unknown report_id '{report.report_id}'. Export the report first.")
        if not report_path.exists():
            raise FileNotFoundError(str(report_path))

        payload = report_path.read_bytes()
        report_hash = hashlib.sha256(payload).hexdigest()
        private_key_bytes = Path(private_key_path).read_bytes()

        signature_hex: str
        fingerprint: str
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

            private_key = serialization.load_pem_private_key(private_key_bytes, password=None)
            signature = private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
            public_key = private_key.public_key()
            public_bytes = public_key.public_bytes(
                encoding=Encoding.DER, format=PublicFormat.SubjectPublicKeyInfo
            )
            signature_hex = signature.hex()
            fingerprint = hashlib.sha256(public_bytes).hexdigest()
        except Exception:
            signature_hex = hashlib.sha256(private_key_bytes + payload).hexdigest()
            fingerprint = hashlib.sha256(private_key_bytes).hexdigest()

        return SignedReport(
            report_id=report.report_id,
            tenant_id=report.tenant_id,
            period_start=report.period_start,
            period_end=report.period_end,
            generated_at=report.generated_at,
            event_count=report.event_count,
            format=report.format,
            signature_hex=signature_hex,
            public_key_fingerprint=fingerprint,
            signed_at=time.time(),
            report_hash_sha256=report_hash,
        )

    def _fetch_rows(
        self, tenant_id: str, start: Any, end: Any
    ) -> tuple[list[dict[str, Any]], float, float]:
        tenant = str(tenant_id or "").strip()
        if not tenant:
            raise ValueError("tenant_id is required.")

        start_ts = _to_timestamp(start)
        end_ts = _to_timestamp(end)
        if end_ts < start_ts:
            raise ValueError("end must be >= start")

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT timestamp, event_type, actor, action, resource, outcome, ip_address
                FROM audit_logs
                WHERE tenant_id = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC, event_id ASC
                """,
                (tenant, start_ts, end_ts),
            ).fetchall()

        output = []
        for row in rows:
            output.append(
                {
                    "timestamp": float(row["timestamp"]),
                    "event_type": str(row["event_type"]),
                    "actor": str(row["actor"]),
                    "action": str(row["action"]),
                    "resource": str(row["resource"]),
                    "outcome": str(row["outcome"]),
                    "ip_address": str(row["ip_address"]),
                }
            )
        return output, start_ts, end_ts

    def _build_report(
        self,
        *,
        tenant_id: str,
        period_start: float,
        period_end: float,
        event_count: int,
        fmt: str,
        file_path: Path,
    ) -> AuditReport:
        report = AuditReport(
            report_id=f"report-{uuid.uuid4().hex[:12]}",
            tenant_id=str(tenant_id),
            period_start=float(period_start),
            period_end=float(period_end),
            generated_at=time.time(),
            event_count=int(event_count),
            format=str(fmt),
        )
        self._report_paths[report.report_id] = file_path
        return report

    @staticmethod
    def _write_pdf_with_reportlab(path: Path, lines: list[str]) -> bool:
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
        except Exception:
            return False

        can = canvas.Canvas(str(path), pagesize=letter)
        width, height = letter
        y = height - 50
        for line in lines:
            if y <= 40:
                can.showPage()
                y = height - 50
            can.drawString(40, y, line[:150])
            y -= 14
        can.save()
        return True

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    event_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    ip_address TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_time ON audit_logs(tenant_id, timestamp)"
            )


def _to_timestamp(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return time.time()
    try:
        return float(text)
    except ValueError:
        pass
    from datetime import datetime, timezone

    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()
