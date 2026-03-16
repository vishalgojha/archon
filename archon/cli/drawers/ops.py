from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import click

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand
from archon.cli.copy import DRAWER_COPY

DRAWER_ID = "ops"
COMMAND_IDS = (
    "ops.serve",
    "ops.health",
    "ops.worker",
    "ops.worker-status",
)
DRAWER_META = DRAWER_COPY[DRAWER_ID]
COMMAND_HELP = DRAWER_META["commands"]


def _counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT status, COUNT(*) FROM worker_tasks GROUP BY status").fetchall()
    counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    for status, value in rows:
        counts[str(status)] = int(value)
    return counts


def _worker_paths():
    from archon.deploy.worker import _runtime_dir, _worker_db_path

    return _runtime_dir, _worker_db_path


class _Serve(ArchonCommand):
    command_id = COMMAND_IDS[0]

    def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        host: str,
        port: int,
        config_path: str,
        kill_port: bool,
    ):
        previous_kill = os.environ.get("ARCHON_KILL_PORT")
        path = Path(config_path)
        if not path.exists():
            from archon.cli.drawers.core import _Init

            _Init(self.bindings).invoke(config_path=config_path)
        session.run_step(0, lambda: path)
        session.run_step(1, self.bindings._load_config, config_path)
        session.update_step(2, "running")
        try:
            if kill_port:
                os.environ["ARCHON_KILL_PORT"] = "1"
            self.bindings._run_api_server_with_env(host=host, port=port)
        finally:
            if previous_kill is None:
                os.environ.pop("ARCHON_KILL_PORT", None)
            else:
                os.environ["ARCHON_KILL_PORT"] = previous_kill
            session.update_step(2, "success")
        return {"host": host, "port": port}


class _Health(ArchonCommand):
    command_id = COMMAND_IDS[1]

    def run(self, session, *, base_url: str, timeout_s: float):  # type: ignore[no-untyped-def,override]
        payload = session.run_step(
            0,
            self.bindings._request_json,
            "GET",
            f"{self.bindings._normalize_base_url(base_url)}/health",
            timeout_s=timeout_s,
        )
        session.run_step(1, lambda: None)
        session.print(
            renderer.detail_panel(
                self.command_id,
                [
                    f"status {payload.get('status', 'unknown')}",
                    f"version {payload.get('version', 'unknown')}",
                    f"db {payload.get('db_status', 'unknown')}",
                ],
            )
        )
        return {
            "status": str(payload.get("status", "unknown")),
            "version": str(payload.get("version", "unknown")),
            "db_status": str(payload.get("db_status", "unknown")),
        }


class _Worker(ArchonCommand):
    command_id = COMMAND_IDS[2]

    def run(self, session, *, config_path: str):  # type: ignore[no-untyped-def,override]
        runtime_dir, worker_db_path = _worker_paths()
        runtime = session.run_step(0, runtime_dir)
        session.run_step(1, worker_db_path)
        session.update_step(2, "running")
        env = dict(self.bindings.os.environ)
        env["ARCHON_CONFIG"] = config_path
        process = subprocess.Popen(
            [sys.executable, "-m", "archon.deploy.worker"],
            cwd=str(Path.cwd()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        try:
            assert process.stdout is not None
            for line in process.stdout:
                click.echo(line.rstrip())
        finally:
            return_code = process.wait()
            session.update_step(2, "success")
        session.print(renderer.detail_panel(self.command_id, [f"runtime {runtime}"]))
        return {"return_code": return_code}


class _WorkerStatus(ArchonCommand):
    command_id = COMMAND_IDS[3]

    def run(self, session):  # type: ignore[no-untyped-def]
        runtime_dir, worker_db_path = _worker_paths()
        session.run_step(0, runtime_dir)
        counts = session.run_step(1, _counts, worker_db_path())
        lines = [f"{key} {value}" for key, value in counts.items()]
        session.run_step(2, lambda: None)
        session.print(renderer.detail_panel(self.command_id, lines))
        return counts


def build_group(bindings):
    @click.group(
        name=DRAWER_ID,
        invoke_without_command=True,
        help=str(DRAWER_META["tagline"]),
    )
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("serve", help=str(COMMAND_HELP[COMMAND_IDS[0]]))
    @click.option("--host", default="127.0.0.1")
    @click.option("--port", default=8000, type=int)
    @click.option("--config", "config_path", default="config.archon.yaml")
    @click.option("--kill-port", is_flag=True, default=False)
    def serve_command(host: str, port: int, config_path: str, kill_port: bool) -> None:
        _Serve(bindings).invoke(
            host=host,
            port=port,
            config_path=config_path,
            kill_port=kill_port,
        )

    @group.command("health", help=str(COMMAND_HELP[COMMAND_IDS[1]]))
    @click.option("--base-url", default="http://127.0.0.1:8000")
    @click.option("--timeout", "timeout_s", default=5.0, type=float)
    def health_command(base_url: str, timeout_s: float) -> None:
        _Health(bindings).invoke(base_url=base_url, timeout_s=timeout_s)

    @group.group(
        "worker",
        invoke_without_command=True,
        help=str(COMMAND_HELP[COMMAND_IDS[2]]),
    )
    @click.option("--config", "config_path", default="config.archon.yaml")
    @click.pass_context
    def worker_command(ctx: click.Context, config_path: str) -> None:
        if ctx.invoked_subcommand is None:
            _Worker(bindings).invoke(config_path=config_path)

    @worker_command.command("status", help=str(COMMAND_HELP[COMMAND_IDS[3]]))
    def worker_status_command() -> None:
        _WorkerStatus(bindings).invoke()

    return group
