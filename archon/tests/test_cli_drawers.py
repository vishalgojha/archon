from __future__ import annotations

from click.testing import CliRunner

from archon.archon_cli import cli
from archon.cli.copy import DRAWER_COPY


def _assert_drawer(drawer_id: str) -> None:
    result = CliRunner().invoke(cli, [drawer_id])
    assert result.exit_code == 0
    drawer = DRAWER_COPY[drawer_id]
    assert str(drawer["title"]) in result.output
    for command_id in drawer["commands"]:
        assert command_id.split(".", 1)[1] in result.output


def test_core_drawer() -> None:
    _assert_drawer("core")


def test_agents_drawer() -> None:
    _assert_drawer("agents")


def test_memory_drawer() -> None:
    _assert_drawer("memory")


def test_evolve_drawer() -> None:
    _assert_drawer("evolve")


def test_skills_drawer() -> None:
    _assert_drawer("skills")


def test_providers_drawer() -> None:
    _assert_drawer("providers")


def test_ops_drawer() -> None:
    _assert_drawer("ops")
