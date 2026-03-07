"""Sandbox subprocess entrypoint for marketplace agent execution."""

from __future__ import annotations

import asyncio
import builtins
import importlib
import json
import math
import os
import sys
import tracemalloc
from typing import Any


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if len(args) < 2:
        _print_json(
            {"error": "usage: python -m archon.marketplace.runner <listing_id> <input_json>"}
        )
        return 1

    _listing_id = str(args[0])
    input_json = str(args[1])
    listing = _load_listing_from_env()

    try:
        input_data = json.loads(input_json)
        if not isinstance(input_data, dict):
            raise ValueError("input_json must decode to an object")
    except Exception as exc:
        _print_json({"error": f"invalid_input:{exc}"})
        return 1

    try:
        _apply_runtime_guards()
        tracemalloc.start()
        result = _execute_listing(listing, input_data)
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        _ = current_bytes
        peak_mb = peak_bytes / (1024.0 * 1024.0)
        memory_limit_mb = _read_int_env("ARCHON_SANDBOX_MEMORY_MB", default=256)
        if peak_mb > float(memory_limit_mb):
            _print_json({"error": "memory_limit_exceeded", "peak_memory_mb": round(peak_mb, 3)})
            return 1

        _print_json(result if isinstance(result, dict) else {"result": result})
        return 0
    except MemoryError:
        _print_json(_memory_limit_payload())
        return 1
    except Exception as exc:
        _print_json({"error": _exception_message(exc)})
        return 1


def _load_listing_from_env() -> dict[str, Any]:
    raw = os.getenv("ARCHON_SANDBOX_LISTING_JSON", "").strip()
    if not raw:
        raise RuntimeError("Missing ARCHON_SANDBOX_LISTING_JSON")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("ARCHON_SANDBOX_LISTING_JSON must decode to an object")
    if not str(parsed.get("entry_point", "")).strip():
        raise RuntimeError("listing.entry_point is required")
    return parsed


def _apply_runtime_guards() -> None:
    memory_mb = _read_int_env("ARCHON_SANDBOX_MEMORY_MB", default=256)
    timeout_s = float(os.getenv("ARCHON_SANDBOX_TIMEOUT_S", "30") or 30)
    cpu_percent = _read_int_env("ARCHON_SANDBOX_CPU_PERCENT", default=25)

    try:
        import resource  # type: ignore

        memory_bytes = max(1, memory_mb) * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        except Exception:
            pass

        cpu_seconds = _cpu_time_limit_seconds(timeout_s=timeout_s, cpu_percent=cpu_percent)
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        except Exception:
            pass
    except Exception:
        pass

    network_enabled = os.getenv("ARCHON_SANDBOX_NETWORK", "0").strip() == "1"
    if not network_enabled:
        import socket

        class _BlockedSocket(socket.socket):
            def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
                raise RuntimeError("Network access is disabled in sandbox.")

        socket.socket = _BlockedSocket  # type: ignore[assignment]

    allowed_raw = os.getenv("ARCHON_SANDBOX_ALLOWED_IMPORTS", "[]")
    try:
        allowed = json.loads(allowed_raw)
    except Exception:
        allowed = []
    if isinstance(allowed, list) and allowed:
        _restrict_imports([str(item) for item in allowed])


def _restrict_imports(allowed_import_roots: list[str]) -> None:
    allowed_roots = {item.split(".", 1)[0] for item in allowed_import_roots if item}
    baseline = {
        "archon",
        "asyncio",
        "builtins",
        "collections",
        "dataclasses",
        "functools",
        "importlib",
        "io",
        "json",
        "math",
        "os",
        "re",
        "sys",
        "time",
        "traceback",
        "typing",
    }

    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
        root = str(name).split(".", 1)[0]
        if root in baseline or root in allowed_roots:
            return original_import(name, globals, locals, fromlist, level)
        raise ImportError(f"Import '{name}' blocked by sandbox allowed_imports policy.")

    builtins.__import__ = guarded_import  # type: ignore[assignment]


def _execute_listing(listing: dict[str, Any], input_data: dict[str, Any]) -> Any:
    entry_point = str(listing.get("entry_point", "")).strip()
    module_name, attr_name = _split_entry_point(entry_point)

    module = importlib.import_module(module_name)
    target = getattr(module, attr_name)
    instance = target() if callable(target) else target

    if not hasattr(instance, "run"):
        raise RuntimeError(f"Entry point '{entry_point}' does not expose a run(input_data) method.")

    run_method = getattr(instance, "run")
    result = run_method(input_data)
    if asyncio.iscoroutine(result):
        return asyncio.run(result)
    return result


def _split_entry_point(entry_point: str) -> tuple[str, str]:
    if ":" in entry_point:
        module_name, attr_name = entry_point.split(":", 1)
        module_name = module_name.strip()
        attr_name = attr_name.strip()
    else:
        module_name, sep, attr_name = entry_point.rpartition(".")
        if not sep:
            raise RuntimeError("entry_point must be in 'module:Class' or 'module.Class' format")
    if not module_name or not attr_name:
        raise RuntimeError("entry_point must be in 'module:Class' or 'module.Class' format")
    return module_name, attr_name


def _read_int_env(name: str, *, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


def _memory_limit_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {"error": "memory_limit_exceeded"}
    if tracemalloc.is_tracing():
        _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        payload["peak_memory_mb"] = round(peak_bytes / (1024.0 * 1024.0), 3)
    return payload


def _cpu_time_limit_seconds(*, timeout_s: float, cpu_percent: int) -> int:
    timeout_seconds = max(1, math.ceil(float(timeout_s)))
    cpu_budget_seconds = max(1, math.ceil(float(timeout_s) * max(cpu_percent, 1) / 100.0))
    return max(timeout_seconds, cpu_budget_seconds)


def _exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return message
    return exc.__class__.__name__.lower()


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
