"""Unit tests for sandbox runner error normalization."""

import json

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
