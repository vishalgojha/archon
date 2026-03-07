"""Tests for the user-facing ARCHON CLI surface."""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from archon.archon_cli import cli


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _test_runtime_dir(name: str) -> Path:
    root = _repo_root() / ".tmp-runtime-tests" / name
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_pyproject_exposes_archon_console_script() -> None:
    pyproject = _repo_root() / "pyproject.toml"
    with pyproject.open("rb") as handle:
        payload = tomllib.load(handle)

    scripts = payload["project"]["scripts"]
    assert scripts["archon"] == "archon.archon_cli:main"
    assert scripts["archon-server"] == "archon.interfaces.api.server:run"


def test_serve_command_invokes_server_runner(monkeypatch: pytest.MonkeyPatch) -> None:
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
    result = runner.invoke(cli, ["serve", "--host", "0.0.0.0", "--port", "9000"])

    assert result.exit_code == 0
    assert captured == {"host": "0.0.0.0", "port": 9000}


def test_serve_command_surfaces_runtime_error_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "archon.archon_cli._load_config",
        lambda path="config.archon.yaml": object(),
    )

    def fake_run_api_server_with_env(*, host: str, port: int) -> None:
        del host, port
        raise RuntimeError("ARCHON server requires websocket support.")

    monkeypatch.setattr("archon.archon_cli._run_api_server_with_env", fake_run_api_server_with_env)

    runner = CliRunner()
    result = runner.invoke(cli, ["serve"])

    assert result.exit_code != 0
    assert "ARCHON server requires websocket support." in result.output


def test_api_server_run_requires_websocket_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    from archon.interfaces.api import server

    monkeypatch.setattr(server, "_has_websocket_transport", lambda: False)

    with pytest.raises(RuntimeError, match="requires websocket support"):
        server.run()


def test_api_server_run_invokes_uvicorn_with_websocket_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from archon.interfaces.api import server

    captured: dict[str, object] = {}
    monkeypatch.setattr(server, "_has_websocket_transport", lambda: True)
    monkeypatch.setenv("ARCHON_RUNTIME_DIR", str(_test_runtime_dir("basic-run")))
    monkeypatch.setattr(server, "_port_is_bindable", lambda host, port: True)

    def fake_uvicorn_run(app_path: str, *, host: str, port: int, reload: bool) -> None:
        captured["app_path"] = app_path
        captured["host"] = host
        captured["port"] = port
        captured["reload"] = reload

    monkeypatch.setattr(server.uvicorn, "run", fake_uvicorn_run)
    monkeypatch.setenv("ARCHON_HOST", "0.0.0.0")
    monkeypatch.setenv("ARCHON_PORT", "8123")

    server.run()

    assert captured == {
        "app_path": "archon.interfaces.api.server:app",
        "host": "0.0.0.0",
        "port": 8123,
        "reload": False,
    }


def test_api_server_run_replaces_previous_managed_server_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from archon.interfaces.api import server

    terminated: list[int] = []
    captured: dict[str, object] = {}
    runtime_dir = _test_runtime_dir("replace-run")

    monkeypatch.setattr(server, "_has_websocket_transport", lambda: True)
    monkeypatch.setenv("ARCHON_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("ARCHON_HOST", "127.0.0.1")
    monkeypatch.setenv("ARCHON_PORT", "8000")
    monkeypatch.setattr(server.os, "getpid", lambda: 9999)
    monkeypatch.setattr(server, "_process_is_running", lambda pid: pid == 4321)
    monkeypatch.setattr(server, "_wait_for_process_exit", lambda pid, timeout_s: True)
    monkeypatch.setattr(server, "_port_is_bindable", lambda host, port: True)

    def fake_terminate_process(pid: int) -> None:
        terminated.append(pid)

    def fake_uvicorn_run(app_path: str, *, host: str, port: int, reload: bool) -> None:
        captured["app_path"] = app_path
        captured["host"] = host
        captured["port"] = port
        captured["reload"] = reload
        lock_path = server._managed_server_lock_path(host, port)
        payload = server._read_managed_server_lock(lock_path)
        captured["lock_pid"] = payload["pid"] if payload else None

    monkeypatch.setattr(server, "_terminate_process", fake_terminate_process)
    monkeypatch.setattr(server.uvicorn, "run", fake_uvicorn_run)

    lock_path = server._managed_server_lock_path("127.0.0.1", 8000)
    server._write_managed_server_lock(lock_path, pid=4321, host="127.0.0.1", port=8000)

    server.run()

    assert terminated == [4321]
    assert captured == {
        "app_path": "archon.interfaces.api.server:app",
        "host": "127.0.0.1",
        "port": 8000,
        "reload": False,
        "lock_pid": 9999,
    }
    assert not lock_path.exists()


def test_api_server_run_rejects_unmanaged_port_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from archon.interfaces.api import server

    monkeypatch.setattr(server, "_has_websocket_transport", lambda: True)
    monkeypatch.setenv("ARCHON_RUNTIME_DIR", str(_test_runtime_dir("unmanaged-port")))
    monkeypatch.setenv("ARCHON_HOST", "127.0.0.1")
    monkeypatch.setenv("ARCHON_PORT", "8000")
    monkeypatch.setattr(server, "_port_is_bindable", lambda host, port: False)

    with pytest.raises(RuntimeError, match="already in use by an unmanaged process"):
        server.run()


def test_health_command_prints_server_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request_json(method: str, url: str, **kwargs):  # type: ignore[no-untyped-def]
        assert method == "GET"
        assert url == "http://127.0.0.1:8000/health"
        assert kwargs["timeout_s"] == 3.5
        return {"status": "ok", "version": "1.2.3", "db_status": "ok", "uptime_s": 12.345}

    monkeypatch.setattr("archon.archon_cli._request_json", fake_request_json)

    runner = CliRunner()
    result = runner.invoke(cli, ["health", "--timeout", "3.5"])

    assert result.exit_code == 0
    assert "Status: ok" in result.output
    assert "Version: 1.2.3" in result.output
    assert "DB: ok" in result.output
    assert "Uptime: 12.35s" in result.output


def test_task_command_posts_to_api_and_prints_result(monkeypatch: pytest.MonkeyPatch) -> None:
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
            "mode": "growth",
            "final_answer": "Run targeted outreach.",
            "confidence": 84,
            "budget": {"spent_usd": 0.42},
        }

    monkeypatch.setattr("archon.archon_cli._create_api_headers", fake_headers)
    monkeypatch.setattr("archon.archon_cli._request_json", fake_request_json)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "task",
            "Increase qualified leads",
            "--mode",
            "auto",
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
        "mode": "growth",
        "context": {"market": "India", "sector": "pharmacy"},
    }
    assert captured["timeout_s"] == 9.0
    assert "Mode:" in result.output
    assert "Run targeted outreach." in result.output
    assert "Confidence: 84%" in result.output
    assert "Budget spent: $0.4200" in result.output


def test_dashboard_and_studio_commands_launch_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    launched: list[str] = []

    def fake_launch(url: str) -> bool:
        launched.append(url)
        return True

    monkeypatch.setattr("click.launch", fake_launch)

    runner = CliRunner()
    dashboard = runner.invoke(cli, ["dashboard", "--base-url", "http://localhost:8100/"])
    studio = runner.invoke(cli, ["studio", "--base-url", "http://localhost:8100/"])

    assert dashboard.exit_code == 0
    assert studio.exit_code == 0
    assert launched == [
        "http://localhost:8100/dashboard",
        "http://localhost:8100/studio",
    ]


def test_metrics_command_raw_outputs_prometheus_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "archon.archon_cli._request_text",
        lambda method, url, **kwargs: "archon_requests_total{method=\"GET\",path=\"/health\",status=\"200\"} 7\n",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["metrics", "--raw"])

    assert result.exit_code == 0
    assert "archon_requests_total" in result.output


def test_traces_command_failed_filters_non_failed_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "archon.archon_cli._request_json",
        lambda method, url, **kwargs: [
            {"span_id": "1", "parent_id": None, "name": "orchestrator.run", "status": "ok", "duration_ms": 12.0},
            {
                "span_id": "2",
                "parent_id": None,
                "name": "llm.call",
                "status": "error",
                "duration_ms": 5.0,
                "error": "boom",
            },
        ],
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["traces", "--failed"])

    assert result.exit_code == 0
    assert "llm.call" in result.output
    assert "orchestrator.run" not in result.output
