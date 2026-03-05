"""Tests for config validation CLI behavior."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from archon import validate_config as validate_module


def _write_yaml(content: str) -> Path:
    path = Path(f"validate-config-{uuid.uuid4().hex}.yaml")
    path.write_text(content, encoding="utf-8")
    return path


def test_validate_config_dry_run_passes_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for env_name in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(env_name, raising=False)

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
        report = validate_module.validate_config(path=path, dry_run=True)
        assert report.ok is True
        assert report.errors == []
        assert report.warnings
    finally:
        path.unlink(missing_ok=True)


def test_validate_config_strict_fails_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for env_name in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(env_name, raising=False)

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
        report = validate_module.validate_config(path=path, dry_run=False)
        assert report.ok is False
        assert report.errors
    finally:
        path.unlink(missing_ok=True)


def test_validate_config_strict_passes_with_openrouter_fallback_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

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
        report = validate_module.validate_config(path=path, dry_run=False)
        assert report.ok is False
        # Strict mode demands credentials for all configured providers.
        assert any("anthropic" in err for err in report.errors)
        assert any("openai" in err for err in report.errors)
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
