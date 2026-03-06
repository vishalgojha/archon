"""Tests for archon.archon_cli commands."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from click.testing import CliRunner
from jose import jwt

from archon.archon_cli import cli


def test_validate_command_calls_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_validate_main(argv):  # type: ignore[no-untyped-def]
        calls.append(list(argv))
        return 0

    monkeypatch.setattr("archon.archon_cli.validate_config_main", fake_validate_main)
    monkeypatch.setattr("archon.archon_cli._load_config", lambda path="config.archon.yaml": object())

    runner = CliRunner()
    result = runner.invoke(cli, ["validate"])
    assert result.exit_code == 0
    assert calls
    assert "--config" in calls[0]


def test_token_create_prints_decodable_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("archon.archon_cli._load_config", lambda path="config.archon.yaml": object())
    runner = CliRunner()
    secret = "test-secret-123"
    result = runner.invoke(
        cli,
        ["token", "create", "--tenant-id", "tenant-x", "--tier", "pro"],
        env={"ARCHON_JWT_SECRET": secret},
    )
    assert result.exit_code == 0
    token = result.output.strip()
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    assert payload["sub"] == "tenant-x"
    assert payload["tier"] == "pro"
    assert payload["type"] == "tenant"


def test_memory_search_formats_results(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeStore:
        def __init__(self):  # noqa: D107
            self.closed = False

        def search(self, query: str, tenant_id: str, top_k: int):  # type: ignore[no-untyped-def]
            assert query == "alpha"
            assert tenant_id == "tenant-a"
            assert top_k == 5
            memory = SimpleNamespace(
                memory_id="mem-1",
                role="assistant",
                content="alpha content response",
            )
            return [SimpleNamespace(memory=memory, similarity=0.9123)]

        def close(self):  # noqa: D401
            self.closed = True

    monkeypatch.setattr("archon.archon_cli.MemoryStore", FakeStore)
    monkeypatch.setattr("archon.archon_cli._load_config", lambda path="config.archon.yaml": object())
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "search", "alpha", "--tenant", "tenant-a", "--top-k", "5"])
    assert result.exit_code == 0
    assert "mem-1" in result.output
    assert "0.912" in result.output
    assert "assistant" in result.output


def test_peers_list_outputs_table(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRegistry:
        async def discover(self, capability_filter):  # type: ignore[no-untyped-def]
            assert capability_filter is None
            return [
                SimpleNamespace(
                    peer_id="peer-1",
                    address="https://peer-1.example.com",
                    capabilities=["debate", "vision"],
                    version="1.2.0",
                )
            ]

        async def aclose(self):
            return None

    monkeypatch.setattr("archon.archon_cli.PeerRegistry", FakeRegistry)
    monkeypatch.setattr("archon.archon_cli._load_config", lambda path="config.archon.yaml": object())
    runner = CliRunner()
    result = runner.invoke(cli, ["peers", "list"])
    assert result.exit_code == 0
    assert "peer-1" in result.output
    assert "https://peer-1.example.com" in result.output
    assert "debate,vision" in result.output


def test_version_command_prints_version_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("archon.archon_cli._resolve_version", lambda: "9.9.9")
    monkeypatch.setattr("archon.archon_cli._resolve_git_sha", lambda: "abc1234")
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert "ARCHON 9.9.9 (git abc1234)" in result.output

