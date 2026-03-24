"""Unit tests for schema-first validation and provider health checks."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

from archon import validate_config as validate_module


def _write_yaml(content: str) -> Path:
    path = Path(f"validate-config-new-{uuid.uuid4().hex}.yaml")
    path.write_text(content, encoding="utf-8")
    return path


def _valid_config_yaml() -> str:
    return """
providers:
  primary: openai
  coding: openai
  vision: openai
  fast: openai
  embedding: ollama
  fallback: openrouter
  ollama_base_url: http://localhost:11434/v1
  openrouter_base_url: https://openrouter.ai/api/v1
  custom_endpoints: []
budget:
  per_request_usd: 0.5
  daily_usd: 5.0
  monthly_usd: 50.0
  alert_threshold: 0.8
tenants:
  - tenant_id: tenant-a
    tier: pro
memory:
  backend: sqlite
  path: archon_memory.sqlite3
evolution:
  enabled: false
  max_experiments_per_day: 0
"""


class _MockResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _MockAsyncClient:
    def __init__(self, *, route_map: dict[str, Any], **_kwargs: Any) -> None:
        self._route_map = route_map

    async def __aenter__(self) -> "_MockAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _MockResponse:
        del headers
        action = self._route_map.get(url, 200)
        if isinstance(action, Exception):
            raise action
        return _MockResponse(int(action))


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, route_map: dict[str, Any]) -> None:
    def _factory(*args: Any, **kwargs: Any) -> _MockAsyncClient:
        del args
        return _MockAsyncClient(route_map=route_map, **kwargs)

    monkeypatch.setattr(validate_module.httpx, "AsyncClient", _factory)


def test_schema_validation_valid_config(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_yaml(_valid_config_yaml())
    try:
        _patch_httpx(monkeypatch, {"https://api.openai.com/v1/models": 200})
        report = validate_module.validate_config(path=config, provider="openai")
        assert report.schema_valid is True
        assert report.ok is True
        assert report.errors == []
    finally:
        config.unlink(missing_ok=True)


def test_schema_validation_rejects_invalid_roles() -> None:
    config = _write_yaml(
        """
providers:
  primary: bad-provider
  coding: openai
  vision: openai
  fast: openai
  embedding: ollama
  fallback: openrouter
budget:
  per_request_usd: 0.5
  daily_usd: 5.0
  monthly_usd: 50.0
  alert_threshold: 0.8
tenants: []
memory:
  backend: sqlite
evolution:
  enabled: false
""",
    )
    try:
        report = validate_module.validate_config(path=config)
        assert report.schema_valid is False
        assert report.ok is False
        assert any("Invalid provider" in err for err in report.errors)
    finally:
        config.unlink(missing_ok=True)


def test_schema_validation_rejects_invalid_tier() -> None:
    config = _write_yaml(
        """
providers:
  primary: openai
  coding: openai
  vision: openai
  fast: openai
  embedding: ollama
  fallback: openrouter
budget:
  per_request_usd: 0.5
  daily_usd: 5.0
  monthly_usd: 50.0
  alert_threshold: 0.8
tenants:
  - tenant_id: tenant-a
    tier: platinum
memory:
  backend: sqlite
evolution:
  enabled: false
""",
    )
    try:
        report = validate_module.validate_config(path=config)
        assert report.schema_valid is False
        assert report.ok is False
        assert any("tier" in err for err in report.errors)
    finally:
        config.unlink(missing_ok=True)


def test_schema_validation_rejects_inverted_budget() -> None:
    config = _write_yaml(
        """
providers:
  primary: openai
  coding: openai
  vision: openai
  fast: openai
  embedding: ollama
  fallback: openrouter
budget:
  per_request_usd: 3.0
  daily_usd: 2.0
  monthly_usd: 1.0
  alert_threshold: 0.8
tenants: []
memory:
  backend: sqlite
evolution:
  enabled: false
""",
    )
    try:
        report = validate_module.validate_config(path=config)
        assert report.schema_valid is False
        assert report.ok is False
        assert any("Budget sanity failed" in err for err in report.errors)
    finally:
        config.unlink(missing_ok=True)


def test_health_check_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_yaml(_valid_config_yaml())
    try:
        _patch_httpx(monkeypatch, {"https://api.openai.com/v1/models": 200})
        report = validate_module.validate_config(path=config, provider="openai")
        item = next(row for row in report.provider_health if row.provider == "openai")
        assert item.status == "PASS"
        assert report.ok is True
    finally:
        config.unlink(missing_ok=True)


def test_health_check_auth_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_yaml(_valid_config_yaml())
    try:
        _patch_httpx(monkeypatch, {"https://api.openai.com/v1/models": 401})
        report = validate_module.validate_config(path=config, provider="openai")
        item = next(row for row in report.provider_health if row.provider == "openai")
        assert item.status == "AUTH_FAILED"
        assert report.ok is False
    finally:
        config.unlink(missing_ok=True)


def test_health_check_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_yaml(_valid_config_yaml())
    try:
        request = httpx.Request("GET", "https://api.openai.com/v1/models")
        _patch_httpx(
            monkeypatch,
            {"https://api.openai.com/v1/models": httpx.ConnectError("boom", request=request)},
        )
        report = validate_module.validate_config(path=config, provider="openai")
        item = next(row for row in report.provider_health if row.provider == "openai")
        assert item.status == "UNREACHABLE"
        assert report.ok is False
    finally:
        config.unlink(missing_ok=True)


def test_health_check_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_yaml(_valid_config_yaml())
    try:
        request = httpx.Request("GET", "https://api.openai.com/v1/models")
        _patch_httpx(
            monkeypatch,
            {"https://api.openai.com/v1/models": httpx.ReadTimeout("slow", request=request)},
        )
        report = validate_module.validate_config(path=config, provider="openai")
        item = next(row for row in report.provider_health if row.provider == "openai")
        assert item.status == "TIMEOUT"
        assert report.ok is False
    finally:
        config.unlink(missing_ok=True)


def test_not_configured_and_skipped_do_not_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_yaml(_valid_config_yaml())
    try:
        _patch_httpx(monkeypatch, {"https://api.openai.com/v1/models": 200})
        not_configured = validate_module.validate_config(path=config, provider="anthropic")
        assert not_configured.ok is True
        assert not_configured.provider_health[0].status == "NOT_CONFIGURED"

        skipped = validate_module.validate_config(path=config, provider="openai")
        statuses = {row.status for row in skipped.provider_health}
        assert "SKIPPED" in statuses
        assert skipped.ok is True
    finally:
        config.unlink(missing_ok=True)


def test_exit_code_logic(monkeypatch: pytest.MonkeyPatch) -> None:
    healthy = _write_yaml(_valid_config_yaml())
    failing = _write_yaml(
        """
providers:
  primary: openai
  coding: openai
  vision: openai
  fast: openai
  embedding: ollama
  fallback: openrouter
budget:
  per_request_usd: 6.0
  daily_usd: 5.0
  monthly_usd: 50.0
  alert_threshold: 0.8
tenants: []
memory:
  backend: sqlite
evolution:
  enabled: false
""",
    )
    try:
        _patch_httpx(monkeypatch, {"https://api.openai.com/v1/models": 200})
        assert validate_module.main(["--config", str(healthy), "--provider", "openai"]) == 0
        assert validate_module.main(["--config", str(failing), "--provider", "openai"]) == 1
    finally:
        healthy.unlink(missing_ok=True)
        failing.unlink(missing_ok=True)


def test_normalize_config_accepts_onboarding_metadata_and_legacy_budget_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_yaml(
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
budget:
  daily_limit_usd: 5.0
  alert_threshold_pct: 80
supervised_mode: true
deployment_mode: personal_assistant
default_tier: free
""",
    )
    try:
        _patch_httpx(
            monkeypatch,
            {
                "https://openrouter.ai/api/v1/models": 200,
                "http://localhost:11434/api/tags": 200,
            },
        )
        report = validate_module.validate_config(path=config)
        assert report.schema_valid is True
        assert report.ok is True
    finally:
        config.unlink(missing_ok=True)
