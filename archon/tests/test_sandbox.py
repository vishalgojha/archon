"""Tests for marketplace subprocess sandbox and runner entrypoint."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from archon.marketplace.sandbox import (
    AgentListing,
    ResourceMonitor,
    ResourceSnapshot,
    SandboxConfig,
    SandboxedAgent,
)

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Sandbox subprocess isolation tests require Unix-like process primitives in CI.",
)

_CREATED_MODULES: list[Path] = []


@pytest.fixture(autouse=True)
def _cleanup_generated_modules() -> None:
    try:
        yield
    finally:
        for path in list(_CREATED_MODULES):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
            cache_dir = Path("__pycache__")
            if cache_dir.exists():
                for cached in cache_dir.glob(f"{path.stem}*.pyc"):
                    cached.unlink(missing_ok=True)
        _CREATED_MODULES.clear()


def _write_temp_module(source: str) -> str:
    module_name = f"_sandbox_agent_{uuid.uuid4().hex[:10]}"
    path = Path(f"{module_name}.py")
    path.write_text(source, encoding="utf-8")
    _CREATED_MODULES.append(path)
    return module_name


def _run_runner_subprocess(
    *,
    entry_point: str,
    input_data: dict[str, object],
    memory_mb: int = 256,
    network: bool = True,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    env = dict(**os.environ)
    env["ARCHON_SANDBOX_LISTING_JSON"] = json.dumps(
        {"listing_id": "listing-1", "entry_point": entry_point}
    )
    env["ARCHON_SANDBOX_MEMORY_MB"] = str(memory_mb)
    env["ARCHON_SANDBOX_CPU_PERCENT"] = "100"
    env["ARCHON_SANDBOX_TIMEOUT_S"] = "30"
    env["ARCHON_SANDBOX_NETWORK"] = "1" if network else "0"
    env["ARCHON_SANDBOX_ALLOWED_IMPORTS"] = "[]"
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "archon.marketplace.runner",
            "listing-1",
            json.dumps(input_data),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    payload = json.loads(lines[-1]) if lines else {}
    return process, payload


@pytest.mark.asyncio
async def test_sandboxed_agent_clean_run_returns_output() -> None:
    module_name = _write_temp_module(
        """
class Agent:
    def run(self, input_data):
        return {"echo": input_data.get("message"), "ok": True}
""".strip()
    )
    sandbox = SandboxedAgent()
    result = await sandbox.run(
        AgentListing(listing_id="listing-ok", entry_point=f"{module_name}:Agent"),
        {"message": "hello"},
        SandboxConfig(timeout_s=5, network=False),
    )
    assert result.exit_code == 0
    assert result.output["echo"] == "hello"
    assert result.timed_out is False


@pytest.mark.asyncio
async def test_sandboxed_agent_timeout_terminates_process() -> None:
    module_name = _write_temp_module(
        """
import time
class Agent:
    def run(self, input_data):
        time.sleep(2)
        return {"ok": True}
""".strip()
    )
    sandbox = SandboxedAgent()
    result = await sandbox.run(
        AgentListing(listing_id="listing-timeout", entry_point=f"{module_name}:Agent"),
        {"message": "hello"},
        SandboxConfig(timeout_s=0.1, network=False),
    )
    assert result.timed_out is True
    assert result.exit_code != 0


@pytest.mark.asyncio
async def test_sandboxed_agent_memory_limit_enforced() -> None:
    module_name = _write_temp_module(
        """
class Agent:
    def run(self, input_data):
        _blob = bytearray(40 * 1024 * 1024)
        return {"size": len(_blob)}
""".strip()
    )
    sandbox = SandboxedAgent()
    result = await sandbox.run(
        AgentListing(listing_id="listing-memory", entry_point=f"{module_name}:Agent"),
        {"message": "hello"},
        SandboxConfig(memory_mb=8, timeout_s=5, network=False),
    )
    assert result.exit_code == 1
    serialized = json.dumps(result.output).lower()
    assert "error" in result.output
    assert "memory_limit_exceeded" in serialized or "memory" in serialized


@pytest.mark.asyncio
async def test_sandboxed_agent_network_blocked_when_disabled() -> None:
    module_name = _write_temp_module(
        """
import socket
class Agent:
    def run(self, input_data):
        socket.socket()
        return {"ok": True}
""".strip()
    )
    sandbox = SandboxedAgent()
    result = await sandbox.run(
        AgentListing(listing_id="listing-network", entry_point=f"{module_name}:Agent"),
        {"message": "hello"},
        SandboxConfig(timeout_s=5, network=False),
    )
    assert result.exit_code == 1
    assert "disabled" in json.dumps(result.output).lower()


@pytest.mark.asyncio
async def test_resource_monitor_snapshot_and_peak_memory() -> None:
    monitor = ResourceMonitor()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(0.2)",
    )
    snapshot = monitor.monitor(process.pid)
    await process.wait()
    polled = await monitor.poll_until_done(process.pid, interval_ms=50)

    assert isinstance(snapshot, ResourceSnapshot)
    assert snapshot.elapsed_s >= 0.0
    assert all(row.elapsed_s >= 0.0 for row in polled)
    assert monitor.peak_memory(polled) >= 0.0


def test_resource_monitor_peak_memory_returns_max() -> None:
    snapshots = [
        ResourceSnapshot(cpu_percent=0.0, memory_mb=1.0, elapsed_s=0.1),
        ResourceSnapshot(cpu_percent=0.0, memory_mb=4.5, elapsed_s=0.2),
        ResourceSnapshot(cpu_percent=0.0, memory_mb=3.2, elapsed_s=0.3),
    ]
    assert ResourceMonitor.peak_memory(snapshots) == 4.5


def test_runner_valid_entrypoint_outputs_json() -> None:
    module_name = _write_temp_module(
        """
class Agent:
    def run(self, input_data):
        return {"value": input_data.get("n", 0) + 1}
""".strip()
    )
    process, payload = _run_runner_subprocess(
        entry_point=f"{module_name}:Agent",
        input_data={"n": 4},
    )
    assert process.returncode == 0
    assert payload["value"] == 5


def test_runner_exception_outputs_error_and_exit_code_1() -> None:
    module_name = _write_temp_module(
        """
class Agent:
    def run(self, input_data):
        raise RuntimeError("boom")
""".strip()
    )
    process, payload = _run_runner_subprocess(
        entry_point=f"{module_name}:Agent",
        input_data={"n": 4},
    )
    assert process.returncode == 1
    assert "error" in payload
    assert "boom" in str(payload["error"]).lower()
