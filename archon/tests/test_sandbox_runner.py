"""Unit tests for sandbox runner error normalization."""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from archon.marketplace import runner
from archon.marketplace.sandbox import AgentListing, SandboxConfig, SandboxedAgent


def test_runner_memory_error_returns_memory_limit_error(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(runner, "_load_listing_from_env", lambda: {"entry_point": "fake:Agent"})
    monkeypatch.setattr(runner, "_apply_runtime_guards", lambda: None)

    def raise_memory_error(_listing: dict[str, object], _input: dict[str, object]) -> object:
        raise MemoryError()

    monkeypatch.setattr(runner, "_execute_listing", raise_memory_error)
    monkeypatch.setattr(runner, "_print_json", lambda payload: captured.append(payload))

    exit_code = runner.main(["listing-1", json.dumps({"message": "hello"})])

    assert exit_code == 1
    assert captured
    assert captured[-1]["error"] == "memory_limit_exceeded"


def test_cpu_time_limit_seconds_never_undercuts_timeout() -> None:
    assert runner._cpu_time_limit_seconds(timeout_s=5.0, cpu_percent=25) == 5
    assert runner._cpu_time_limit_seconds(timeout_s=0.1, cpu_percent=25) == 1
    assert runner._cpu_time_limit_seconds(timeout_s=5.0, cpu_percent=200) == 10


def test_apply_runtime_guards_skips_cpu_rlimit_by_default(monkeypatch) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []
    fake_resource = SimpleNamespace(
        RLIMIT_AS=1,
        RLIMIT_CPU=2,
        setrlimit=lambda kind, limits: calls.append((kind, limits)),
    )

    monkeypatch.setitem(sys.modules, "resource", fake_resource)
    monkeypatch.setenv("ARCHON_SANDBOX_MEMORY_MB", "32")
    monkeypatch.setenv("ARCHON_SANDBOX_TIMEOUT_S", "5")
    monkeypatch.setenv("ARCHON_SANDBOX_CPU_PERCENT", "25")
    monkeypatch.setenv("ARCHON_SANDBOX_NETWORK", "1")
    monkeypatch.setenv("ARCHON_SANDBOX_ALLOWED_IMPORTS", "[]")
    monkeypatch.delenv("ARCHON_SANDBOX_ENFORCE_CPU_RLIMIT", raising=False)

    runner._apply_runtime_guards()

    assert (fake_resource.RLIMIT_AS, (32 * 1024 * 1024, 32 * 1024 * 1024)) in calls
    assert all(kind != fake_resource.RLIMIT_CPU for kind, _ in calls)


def test_apply_runtime_guards_sets_cpu_rlimit_when_opted_in(monkeypatch) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []
    fake_resource = SimpleNamespace(
        RLIMIT_AS=1,
        RLIMIT_CPU=2,
        setrlimit=lambda kind, limits: calls.append((kind, limits)),
    )

    monkeypatch.setitem(sys.modules, "resource", fake_resource)
    monkeypatch.setenv("ARCHON_SANDBOX_MEMORY_MB", "32")
    monkeypatch.setenv("ARCHON_SANDBOX_TIMEOUT_S", "5")
    monkeypatch.setenv("ARCHON_SANDBOX_CPU_PERCENT", "25")
    monkeypatch.setenv("ARCHON_SANDBOX_NETWORK", "1")
    monkeypatch.setenv("ARCHON_SANDBOX_ALLOWED_IMPORTS", "[]")
    monkeypatch.setenv("ARCHON_SANDBOX_ENFORCE_CPU_RLIMIT", "1")

    runner._apply_runtime_guards()

    assert (fake_resource.RLIMIT_AS, (32 * 1024 * 1024, 32 * 1024 * 1024)) in calls
    assert (fake_resource.RLIMIT_CPU, (5, 6)) in calls


@pytest.mark.asyncio
async def test_sandboxed_agent_overrides_cpu_rlimit_env_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_env: dict[str, str] = {}

    class _FakeProcess:
        pid = 321
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b'{"ok": true}\n', b""

    async def fake_create_subprocess_exec(*_args, **kwargs):  # type: ignore[no-untyped-def]
        captured_env.update(kwargs["env"])
        return _FakeProcess()

    monkeypatch.setenv("ARCHON_SANDBOX_ENFORCE_CPU_RLIMIT", "1")
    monkeypatch.setenv("COV_CORE_SOURCE", "archon")
    monkeypatch.setenv("COVERAGE_PROCESS_START", "/tmp/.coveragerc")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "archon/tests/test_sandbox_runner.py::test")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    sandbox = SandboxedAgent()
    result = await sandbox.run(
        AgentListing(listing_id="listing-1", entry_point="fake.module:Agent"),
        {"message": "hello"},
        SandboxConfig(),
    )

    assert result.exit_code == 0
    assert result.output == {"ok": True}
    assert captured_env["ARCHON_SANDBOX_ENFORCE_CPU_RLIMIT"] == "0"
    assert "COV_CORE_SOURCE" not in captured_env
    assert "COVERAGE_PROCESS_START" not in captured_env
    assert "PYTEST_CURRENT_TEST" not in captured_env


@pytest.mark.asyncio
async def test_sandboxed_agent_enables_cpu_rlimit_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_env: dict[str, str] = {}

    class _FakeProcess:
        pid = 654
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b'{"ok": true}\n', b""

    async def fake_create_subprocess_exec(*_args, **kwargs):  # type: ignore[no-untyped-def]
        captured_env.update(kwargs["env"])
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    sandbox = SandboxedAgent()
    await sandbox.run(
        AgentListing(listing_id="listing-1", entry_point="fake.module:Agent"),
        {"message": "hello"},
        SandboxConfig(enforce_cpu_rlimit=True),
    )

    assert captured_env["ARCHON_SANDBOX_ENFORCE_CPU_RLIMIT"] == "1"
