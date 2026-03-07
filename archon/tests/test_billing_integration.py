"""Integration test for task spend -> billing usage -> invoice flow."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from archon.interfaces.api.server import app


def _auth_headers(*, tenant: str = "tenant-a", tier: str = "business") -> dict[str, str]:
    token = jwt.encode(
        {"sub": tenant, "tier": tier},
        "archon-dev-secret-change-me-32-bytes",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _tmp_db(name: str) -> Path:
    root = Path("archon/tests/_tmp_billing_integration")
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{name}-{uuid.uuid4().hex[:8]}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "db.sqlite3"


def _tmp_config(name: str) -> Path:
    path = _tmp_db(name).with_name("config.archon.yaml")
    path.write_text(
        """
byok:
  primary: openrouter
  coding: openrouter
  vision: openrouter
  fast: openrouter
  embedding: ollama
  fallback: openrouter
  budget_per_task_usd: 0.5
  budget_per_month_usd: 150.0
  ollama_base_url: http://localhost:11434/v1
  openrouter_base_url: https://openrouter.ai/api/v1
  custom_endpoints: []
""".strip(),
        encoding="utf-8",
    )
    return path


def test_task_cost_is_metered_into_billing_summary_and_invoice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("ARCHON_BILLING_DB", str(_tmp_db("billing")))
    monkeypatch.setenv("ARCHON_ANALYTICS_DB", str(_tmp_db("analytics")))
    monkeypatch.setenv("ARCHON_CONFIG", str(_tmp_config("config")))

    with TestClient(app) as client:
        subscription = client.post(
            "/v1/billing/subscription",
            json={"plan_id": "growth"},
            headers=_auth_headers(),
        )
        task = client.post(
            "/v1/tasks",
            json={"goal": "Summarize the migration plan " * 200, "mode": "debate"},
            headers=_auth_headers(),
        )
        summary = client.get("/v1/billing/summary", headers=_auth_headers())
        invoice = client.post(
            "/v1/billing/invoices/generate",
            json={},
            headers=_auth_headers(),
        )

    assert subscription.status_code == 200
    assert task.status_code == 200
    assert summary.status_code == 200
    assert invoice.status_code == 200
    assert summary.json()["usage_summary"]["model_spend_usd"] > 0
    assert invoice.json()["invoice"]["metadata"]["usage_summary"]["model_spend_usd"] > 0
