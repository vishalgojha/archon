"""Unit tests for sandbox runner error normalization."""

import json
import sys
from types import SimpleNamespace

from archon.marketplace import runner


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
