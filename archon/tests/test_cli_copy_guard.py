from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from archon.archon_cli import cli
from archon.cli import drawers as drawer_package
from archon.cli.copy import COMMAND_COPY, DRAWER_COPY
from archon.cli.registry import get_drawers


def _drawer_paths() -> list[Path]:
    return [Path(drawer.__file__).resolve() for drawer in get_drawers()]


def test_every_drawer_has_copy() -> None:
    assert {drawer.drawer_id for drawer in get_drawers()} == set(DRAWER_COPY)


def test_every_command_has_copy() -> None:
    missing = [
        command_id
        for drawer in get_drawers()
        for command_id in drawer.command_ids
        if command_id not in COMMAND_COPY
    ]
    assert missing == []


def test_registry_discovers_every_drawer_file() -> None:
    drawer_dir = Path(drawer_package.__file__).resolve().parent
    expected = {
        f"archon.cli.drawers.{path.stem}"
        for path in drawer_dir.glob("*.py")
        if path.name != "__init__.py"
    }
    assert {drawer.module_path for drawer in get_drawers()} == expected


def test_no_inline_prose_in_drawers() -> None:
    for path in _drawer_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert len(node.value) <= 60, f"{path.name}: {node.value!r}"


def test_bare_archon_prints_all_drawers() -> None:
    result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0
    for drawer in DRAWER_COPY.values():
        assert str(drawer["title"]) in result.output


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
