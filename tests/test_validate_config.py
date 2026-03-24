"""Tests for config validation CLI behavior."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from archon import validate_config as validate_module


def _mock_health(
    monkeypatch: pytest.MonkeyPatch, status_map: dict[str, validate_module.ProviderStatus]
) -> None:
    def _fake_ping(providers, checks, *, timeout_seconds):  # type: ignore[no-untyped-def]
        rows = []
        for name in sorted(checks):
            rows.append(
                validate_module.ProviderHealth(
                    provider=name,
                    status=status_map.get(name, "PASS"),
                    detail="mocked",
                )
            )
        return rows

    monkeypatch.setattr(validate_module, "_ping_configured_providers", _fake_ping)


def _write_yaml(content: str) -> Path:
    path = Path(f"validate-config-{uuid.uuid4().hex}.yaml")
    path.write_text(content, encoding="utf-8")
    return path


def test_validate_config_passes_with_mocked_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_health(monkeypatch, {})

    path = _write_yaml("""
byok:
  primary: anthropic
  coding: openai
  vision: openai
  fast: groq
  embedding: ollama
  fallback: openrouter
""")
    try:
        report = validate_module.validate_config(path=path)
        assert report.ok is True
        assert report.errors == []
        assert report.provider_health
    finally:
        path.unlink(missing_ok=True)


def test_validate_config_reports_failed_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_health(monkeypatch, {"anthropic": "FAIL"})

    path = _write_yaml("""
byok:
  primary: anthropic
  coding: openai
  vision: openai
  fast: groq
  embedding: ollama
  fallback: openrouter
""")
    try:
        report = validate_module.validate_config(path=path)
        assert report.ok is False
        assert report.errors
    finally:
        path.unlink(missing_ok=True)


def test_validate_config_reports_not_configured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_health(monkeypatch, {})

    path = _write_yaml("""
byok:
  embedding: ollama
""")
    try:
        report = validate_module.validate_config(path=path, provider="openai")
        assert report.ok is True
        assert any(row.status == "NOT_CONFIGURED" for row in report.provider_health)
    finally:
        path.unlink(missing_ok=True)


def test_validate_config_main_returns_error_for_schema_failure() -> None:
    path = _write_yaml("""
byok:
  primary:
    not: a-string
""")
    try:
        exit_code = validate_module.main(["--config", str(path)])
        assert exit_code == 1
    finally:
        path.unlink(missing_ok=True)
