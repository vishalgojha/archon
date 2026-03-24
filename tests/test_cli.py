"""Tests for the minimal ARCHON CLI surface."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from archon.archon_cli import cli


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_pyproject_exposes_archon_console_script() -> None:
    pyproject = _repo_root() / "pyproject.toml"
    with pyproject.open("rb") as handle:
        payload = tomllib.load(handle)

    scripts = payload["project"]["scripts"]
    assert scripts["archon"] == "archon.archon_cli:main"
    assert scripts["archon-server"] == "archon.interfaces.api.server:run"


def test_ops_serve_invokes_server_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "archon.archon_cli._load_config",
        lambda path="config.archon.yaml": object(),
    )

    def fake_run_api_server_with_env(*, host: str, port: int) -> None:
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr("archon.archon_cli._run_api_server_with_env", fake_run_api_server_with_env)

    runner = CliRunner()
    result = runner.invoke(cli, ["ops", "serve", "--host", "0.0.0.0", "--port", "9000"])

    assert result.exit_code == 0
    assert captured == {"host": "0.0.0.0", "port": 9000}


def test_ops_health_requests_health(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request_json(method: str, url: str, **kwargs):  # type: ignore[no-untyped-def]
        assert method == "GET"
        assert url == "http://127.0.0.1:8000/health"
        assert kwargs["timeout_s"] == 3.5
        return {"status": "ok", "version": "1.2.3", "git_sha": "abc1234", "uptime_s": 12.345}

    monkeypatch.setattr("archon.archon_cli._request_json", fake_request_json)

    runner = CliRunner()
    result = runner.invoke(cli, ["ops", "health", "--timeout", "3.5"])

    assert result.exit_code == 0
    assert "status ok" in result.output.lower()


def test_agents_task_posts_to_api(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_headers(*, token=None, tenant_id="default", tier="pro"):  # type: ignore[no-untyped-def]
        captured["token"] = token
        captured["tenant_id"] = tenant_id
        captured["tier"] = tier
        return {"Authorization": "Bearer fake-token"}

    def fake_request_json(method: str, url: str, **kwargs):  # type: ignore[no-untyped-def]
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["json_body"] = kwargs["json_body"]
        captured["timeout_s"] = kwargs["timeout_s"]
        return {
            "mode": "debate",
            "final_answer": "Done.",
            "confidence": 84,
            "budget": {"spent_usd": 0.42},
        }

    monkeypatch.setattr("archon.archon_cli._create_api_headers", fake_headers)
    monkeypatch.setattr("archon.archon_cli._request_json", fake_request_json)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "agents",
            "task",
            "Increase qualified leads",
            "--tenant-id",
            "tenant-a",
            "--tier",
            "enterprise",
            "--context",
            '{"market":"India","sector":"pharmacy"}',
            "--timeout",
            "9",
        ],
    )

    assert result.exit_code == 0
    assert captured["tenant_id"] == "tenant-a"
    assert captured["tier"] == "enterprise"
    assert captured["method"] == "POST"
    assert captured["url"] == "http://127.0.0.1:8000/v1/tasks"
    assert captured["headers"] == {"Authorization": "Bearer fake-token"}
    assert captured["json_body"] == {
        "goal": "Increase qualified leads",
        "mode": "debate",
        "context": {"market": "India", "sector": "pharmacy"},
    }
    assert captured["timeout_s"] == 9.0
    assert "confidence" in result.output.lower()


def test_core_chat_launches_agentic_session(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_agentic_tui(
        *,
        config: object,
        initial_mode: str,
        initial_context: dict[str, object],
        config_path: str,
        onboarding: object,
        show_launcher: bool,
    ) -> None:
        captured["config"] = config
        captured["initial_mode"] = initial_mode
        captured["initial_context"] = initial_context
        captured["config_path"] = config_path
        captured["show_launcher"] = show_launcher
        captured["onboarding"] = onboarding

    config = object()
    monkeypatch.setattr("archon.archon_cli._load_config", lambda path="config.archon.yaml": config)
    monkeypatch.setattr("archon.cli.drawers.core.run_agentic_tui", fake_run_agentic_tui)

    runner = CliRunner()
    result = runner.invoke(cli, ["core", "chat", "--mode", "debate"])

    assert result.exit_code == 0
    assert captured["initial_mode"] == "debate"
    assert captured["onboarding"] is not None


def test_core_studio_prints_launch_steps() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["core", "studio"])

    assert result.exit_code == 0
    assert "core.studio" in result.output
    assert "npm run dev" in result.output


def test_version_command_outputs_version() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])

    assert result.exit_code == 0
    assert "ARCHON" in result.output
