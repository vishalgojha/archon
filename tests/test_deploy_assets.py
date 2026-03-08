"""Tests for deploy assets, validator, and CLI wiring."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from archon.archon_cli import cli
from archon.deploy.validator import validate_all


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_deploy_assets_validate_and_render() -> None:
    report = validate_all(_repo_root())

    assert report["ok"] is True
    assert "archon-api" in report["compose"]["services"]
    assert "otel-collector" in report["observability"]["services"]
    assert "traces" in report["otel"]["pipelines"]
    assert "deployment.yaml" in report["helm"]["rendered_templates"]
    assert "secret.yaml" in report["helm"]["rendered_templates"]


def test_deploy_validate_cli_command_succeeds() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["deploy", "validate", "--root", str(_repo_root())])

    assert result.exit_code == 0
    assert "compose ok: True" in result.output
    assert "observability ok: True" in result.output
    assert "otel ok: True" in result.output
    assert "helm ok: True" in result.output
