"""Isolated subprocess sandbox for third-party marketplace agents."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional dependency
    import psutil
except Exception:  # pragma: no cover - optional dependency
    psutil = None  # type: ignore[assignment]


@dataclass(slots=True, frozen=True)
class AgentListing:
    """Marketplace listing descriptor used for sandbox execution."""

    listing_id: str
    entry_point: str
    name: str | None = None


@dataclass(slots=True, frozen=True)
class SandboxConfig:
    memory_mb: int = 256
    cpu_percent: int = 25
    enforce_cpu_rlimit: bool = False
    timeout_s: float = 30.0
    network: bool = False
    allowed_imports: list[str] | None = None


@dataclass(slots=True, frozen=True)
class SandboxResult:
    output: dict[str, Any]
    stdout: str
    stderr: str
    exit_code: int
    cpu_time_s: float
    peak_memory_mb: float
    timed_out: bool


@dataclass(slots=True, frozen=True)
class ResourceSnapshot:
    cpu_percent: float
    memory_mb: float
    elapsed_s: float


class ResourceMonitor:
    """Polls process CPU/memory usage snapshots."""

    def __init__(self) -> None:
        self._started_at: dict[int, float] = {}

    def monitor(self, pid: int) -> ResourceSnapshot:
        now = time.monotonic()
        started = self._started_at.setdefault(int(pid), now)
        elapsed = max(0.0, now - started)

        cpu_percent = 0.0
        memory_mb = 0.0
        if psutil is not None:
            try:
                proc = psutil.Process(int(pid))
                cpu_percent = float(proc.cpu_percent(interval=0.0))
                memory_mb = float(proc.memory_info().rss) / (1024.0 * 1024.0)
            except Exception:
                pass

        return ResourceSnapshot(cpu_percent=cpu_percent, memory_mb=memory_mb, elapsed_s=elapsed)

    async def poll_until_done(self, pid: int, interval_ms: int = 100) -> list[ResourceSnapshot]:
        snapshots: list[ResourceSnapshot] = []
        interval_s = max(0.01, float(interval_ms) / 1000.0)

        while True:
            snapshots.append(self.monitor(pid))
            if not _pid_exists(pid):
                break
            await asyncio.sleep(interval_s)
        return snapshots

    @staticmethod
    def peak_memory(snapshots: list[ResourceSnapshot]) -> float:
        if not snapshots:
            return 0.0
        return max(row.memory_mb for row in snapshots)


class SandboxedAgent:
    """Runs marketplace agents in isolated subprocesses with execution limits."""

    def __init__(
        self,
        *,
        runner_module: str = "archon.marketplace.runner",
        monitor: ResourceMonitor | None = None,
    ) -> None:
        self.runner_module = runner_module
        self.monitor = monitor or ResourceMonitor()

    async def run(
        self,
        listing: AgentListing,
        input_data: dict[str, Any],
        config: SandboxConfig,
    ) -> SandboxResult:
        env = _sandbox_env(os.environ)
        env["ARCHON_SANDBOX_LISTING_JSON"] = json.dumps(
            {
                "listing_id": listing.listing_id,
                "entry_point": listing.entry_point,
                "name": listing.name,
            },
            separators=(",", ":"),
        )
        env["ARCHON_SANDBOX_MEMORY_MB"] = str(max(1, int(config.memory_mb)))
        env["ARCHON_SANDBOX_CPU_PERCENT"] = str(max(1, int(config.cpu_percent)))
        env["ARCHON_SANDBOX_ENFORCE_CPU_RLIMIT"] = "1" if bool(config.enforce_cpu_rlimit) else "0"
        env["ARCHON_SANDBOX_TIMEOUT_S"] = str(float(config.timeout_s))
        env["ARCHON_SANDBOX_NETWORK"] = "1" if config.network else "0"
        env["ARCHON_SANDBOX_ALLOWED_IMPORTS"] = json.dumps(
            config.allowed_imports or [], separators=(",", ":")
        )

        command = [
            sys.executable,
            "-m",
            self.runner_module,
            str(listing.listing_id),
            json.dumps(input_data, separators=(",", ":")),
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(Path.cwd()),
        )

        monitor_task = asyncio.create_task(
            self.monitor.poll_until_done(process.pid, interval_ms=100)
        )
        timed_out = False
        stdout_bytes: bytes = b""
        stderr_bytes: bytes = b""
        started = time.monotonic()

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=max(0.05, float(config.timeout_s)),
            )
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()
        finally:
            snapshots: list[ResourceSnapshot]
            try:
                snapshots = await asyncio.wait_for(monitor_task, timeout=2.0)
            except Exception:
                monitor_task.cancel()
                snapshots = []

        elapsed = max(0.0, time.monotonic() - started)
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        output = _parse_stdout_json(stdout_text)

        return SandboxResult(
            output=output,
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=int(process.returncode if process.returncode is not None else 1),
            cpu_time_s=elapsed,
            peak_memory_mb=self.monitor.peak_memory(snapshots),
            timed_out=timed_out,
        )


def _pid_exists(pid: int) -> bool:
    if psutil is not None:
        try:
            return psutil.pid_exists(int(pid))
        except Exception:
            return False

    if int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except Exception:
        return False
    return True


def _parse_stdout_json(stdout_text: str) -> dict[str, Any]:
    payload = str(stdout_text or "").strip()
    if not payload:
        return {}

    for line in reversed(payload.splitlines()):
        blob = line.strip()
        if not blob:
            continue
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        return {"result": parsed}

    return {"raw": payload}


def _sandbox_env(source: dict[str, str]) -> dict[str, str]:
    """Drop test harness env that can leak into sandboxed subprocesses."""

    blocked_keys = {
        "COVERAGE_PROCESS_CONFIG",
        "COVERAGE_PROCESS_START",
        "PYTEST_CURRENT_TEST",
    }
    return {
        key: value
        for key, value in source.items()
        if key not in blocked_keys and not key.startswith("COV_CORE_")
    }
