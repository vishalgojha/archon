"""Tests for SOC2 audit export, retention policy, and encryption layer."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

import pytest

from archon.compliance.audit_export import SOC2AuditExporter
from archon.compliance.encryption import EncryptionLayer
from archon.compliance.retention import DataRetentionPolicy, RetentionRule


def _tmp_dir(name: str) -> Path:
    root = Path("archon/tests/_tmp_compliance")
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{name}-{uuid.uuid4().hex[:8]}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_private_key(path: Path) -> None:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        path.write_bytes(pem)
    except Exception:
        path.write_text("fallback-private-key", encoding="utf-8")


def test_soc2_audit_exporter_csv_json_and_signature_hash() -> None:
    tmp = _tmp_dir("audit")
    db_path = tmp / "audit.sqlite3"
    exporter = SOC2AuditExporter(db_path=db_path)

    now = time.time()
    for idx in range(3):
        exporter.log_event(
            tenant_id="tenant-a",
            event_type="approval_granted",
            actor=f"agent-{idx}",
            action="approve",
            resource=f"task-{idx}",
            outcome="success",
            ip_address="203.0.113.10",
            timestamp=now - idx,
        )

    start, end = now - 100, now + 100
    csv_path = tmp / "audit.csv"
    csv_report = exporter.export_csv("tenant-a", start, end, csv_path)
    assert csv_report.event_count == 3

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert reader.fieldnames == [
        "timestamp",
        "event_type",
        "actor",
        "action",
        "resource",
        "outcome",
        "ip_address",
    ]
    assert len(rows) == 3

    json_path = tmp / "audit.jsonl"
    json_report = exporter.export_json("tenant-a", start, end, json_path)
    assert json_report.event_count == 3
    json_rows = [
        json.loads(line)
        for line in json_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(json_rows) == 3
    assert all("event_type" in row for row in json_rows)

    key_path = tmp / "private_key.pem"
    _write_private_key(key_path)
    signed = exporter.sign_report(csv_report, key_path)

    assert signed.signature_hex
    expected_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    assert signed.report_hash_sha256 == expected_hash


def test_data_retention_apply_delete_removes_old_rows() -> None:
    tmp = _tmp_dir("retention-delete")
    db_path = tmp / "retention.sqlite3"
    policy = DataRetentionPolicy(db_path=db_path)

    old_ts = time.time() - (45 * 86400)
    new_ts = time.time() - (5 * 86400)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions(session_id, tenant_id, created_at, email, phone, name, data_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("s-old", "tenant-a", old_ts, "old@example.com", "999", "Old Name", "{}"),
        )
        conn.execute(
            "INSERT INTO sessions(session_id, tenant_id, created_at, email, phone, name, data_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("s-new", "tenant-a", new_ts, "new@example.com", "111", "New Name", "{}"),
        )

    result = policy.apply(RetentionRule(entity_type="session", retention_days=30, action="delete"))
    assert result.processed_count == 1
    assert result.action_taken == "delete"

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
    assert row is not None
    assert int(row[0]) == 1


def test_data_retention_apply_anonymize_hashes_email() -> None:
    tmp = _tmp_dir("retention-anon")
    db_path = tmp / "retention.sqlite3"
    policy = DataRetentionPolicy(db_path=db_path)

    original_email = "pii@example.com"
    old_ts = time.time() - (45 * 86400)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions(session_id, tenant_id, created_at, email, phone, name, data_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("s-anon", "tenant-a", old_ts, original_email, "123", "Jane", "{}"),
        )

    result = policy.apply(
        RetentionRule(entity_type="session", retention_days=30, action="anonymize")
    )
    assert result.processed_count == 1

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT email FROM sessions WHERE session_id = ?", ("s-anon",)
        ).fetchone()
    assert row is not None
    assert row[0] == hashlib.sha256(original_email.encode("utf-8")).hexdigest()


def test_data_retention_dry_run_and_schedule_all() -> None:
    tmp = _tmp_dir("retention-dry")
    db_path = tmp / "retention.sqlite3"

    dry_policy = DataRetentionPolicy(db_path=db_path, dry_run=True)
    old_ts = time.time() - (45 * 86400)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO content_pieces(content_piece_id, tenant_id, created_at, title, body, email, phone, name, archived) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("cp-1", "tenant-a", old_ts, "Title", "Body", "a@example.com", "123", "Jane", 0),
        )
        conn.execute(
            "INSERT INTO sessions(session_id, tenant_id, created_at, email, phone, name, data_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("s-schedule", "tenant-a", old_ts, "b@example.com", "456", "John", "{}"),
        )

    dry_result = dry_policy.apply(
        RetentionRule(entity_type="content_piece", retention_days=30, action="delete")
    )
    assert dry_result.processed_count == 1
    assert dry_result.action_taken.startswith("dry_run")

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM content_pieces WHERE content_piece_id = 'cp-1'"
        ).fetchone()
    assert row is not None
    assert int(row[0]) == 1

    policy = DataRetentionPolicy(db_path=db_path)
    results = policy.schedule_all(
        [
            RetentionRule(entity_type="session", retention_days=30, action="delete"),
            RetentionRule(entity_type="content_piece", retention_days=30, action="archive"),
        ]
    )
    assert len(results) == 2
    assert all(result.processed_count >= 1 for result in results)


def test_encryption_layer_roundtrip_derive_and_rotate() -> None:
    master = b"m" * 32
    key_a = EncryptionLayer.derive_key("tenant-a", master)
    key_b = EncryptionLayer.derive_key("tenant-b", master)
    assert key_a != key_b

    encrypted = EncryptionLayer.encrypt("hello world", key_a)
    decrypted = EncryptionLayer.decrypt(encrypted, key_a)
    assert decrypted == "hello world"

    old_key = b"o" * 32
    new_key = b"n" * 32
    record = EncryptionLayer.encrypt("rotate me", old_key)
    rotated = EncryptionLayer.rotate_key(old_key, new_key, [record])
    assert rotated == 1
    assert EncryptionLayer.decrypt(record, new_key) == "rotate me"
    with pytest.raises(Exception):
        EncryptionLayer.decrypt(record, old_key)
