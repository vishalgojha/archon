from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from click.testing import CliRunner

from archon.archon_cli import cli
from archon.cli.copy import COMMAND_COPY, DRAWER_COPY, FLOW_COPY
from archon.cli.main import DRAWER_MODULES, REGISTERED_COMMANDS, REGISTERED_DRAWERS


def _drawer_paths() -> list[Path]:
    return [Path(module.__file__).resolve() for module in DRAWER_MODULES]


def test_every_drawer_has_copy() -> None:
    assert set(REGISTERED_DRAWERS) == set(DRAWER_COPY)


def test_every_command_has_copy() -> None:
    missing = [command_id for command_id in REGISTERED_COMMANDS if command_id not in COMMAND_COPY]
    assert missing == []


def test_no_inline_prose_in_drawers() -> None:
    for path in _drawer_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert len(node.value) <= 60, f"{path.name}: {node.value!r}"


def test_placeholder_commands_no_traceback() -> None:
    runner = CliRunner()
    cases = [
        ["vision", "inspect"],
        ["vision", "act"],
        ["web", "crawl"],
        ["web", "optimize"],
        ["evolve", "plan"],
        ["evolve", "apply"],
        ["federation", "peers"],
        ["federation", "sync"],
        ["marketplace", "payouts"],
        ["marketplace", "earnings"],
        ["memory", "export"],
    ]
    for argv in cases:
        result = runner.invoke(cli, argv)
        assert result.exit_code == 0, argv
        assert FLOW_COPY["placeholder"]["title"] in result.output
        assert "Traceback" not in result.output


def test_bare_archon_prints_all_drawers() -> None:
    result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0
    for drawer in DRAWER_COPY.values():
        assert drawer["title"] in result.output


def test_init_flow_completes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("archon.archon_cli._validate_openai_key", lambda key, timeout_s=5.0: True)
    monkeypatch.setattr(
        "archon.archon_cli._probe_ollama",
        lambda timeout_s=2.0: {
            "reachable": True,
            "models": ["llama3.2"],
            "detail": "reachable",
        },
    )
    monkeypatch.setattr(
        "archon.cli.drawers.core.validate_config",
        lambda *args, **kwargs: SimpleNamespace(
            ok=True,
            schema_valid=True,
            provider_health=[],
            failed_provider_checks=[],
        ),
    )
    runner = CliRunner()
    runtime_dir = Path("archon/tests/_tmp_cli_copy_guard") / uuid.uuid4().hex[:8]
    runtime_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(runtime_dir)
    result = runner.invoke(cli, ["init"], input="openai\nsk-test\nopenai\n5.00\n")
    assert result.exit_code == 0
    assert Path("config.archon.yaml").exists()
    assert "ARCHON is ready" in result.output
