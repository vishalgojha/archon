from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import click

from archon.cli.base_command import ArchonCommand
from archon.cli import renderer
from archon.deploy.worker import _runtime_dir, _worker_db_path

DRAWER_ID = "ops"
COMMAND_IDS = (
    "ops.serve",
    "ops.health",
    "ops.monitor",
    "ops.worker",
    "ops.worker-status",
)


def _counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) "
            "FROM worker_tasks "
            "GROUP BY status"
        ).fetchall()
    counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    for status, value in rows:
        counts[str(status)] = int(value)
    return counts


class _Serve(ArchonCommand):
    command_id = COMMAND_IDS[0]

    def run(self, session, *, host: str, port: int, config_path: str):  # type: ignore[no-untyped-def]
        path = Path(config_path)
        if not path.exists():
            from archon.cli.drawers.core import _Init

            _Init(self.bindings).invoke(config_path=config_path)
        session.run_step(0, lambda: path)
        session.run_step(1, self.bindings._load_config, config_path)
        session.update_step(2, "running")
        try:
            self.bindings._run_api_server_with_env(host=host, port=port)
        finally:
            session.update_step(2, "success")
        return {"host": host, "port": port}


class _Health(ArchonCommand):
    command_id = COMMAND_IDS[1]

    def run(self, session, *, base_url: str, timeout_s: float):  # type: ignore[no-untyped-def]
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


class _Monitor(ArchonCommand):
    command_id = COMMAND_IDS[2]

    def run(self, session, *, base_url: str, timeout_s: float, interval: float):  # type: ignore[no-untyped-def]
        normalized = self.bindings._normalize_base_url(base_url)
        iterations = 0
        session.update_step(0, "running")
        try:
            while True:
                health = self.bindings._request_json(
                    "GET",
                    f"{normalized}/health",
                    timeout_s=timeout_s,
                )
                metrics = self.bindings._request_text(
                    "GET",
                    f"{normalized}/metrics",
                    timeout_s=timeout_s,
                )
                spans = self.bindings._request_json(
                    "GET",
                    f"{normalized}/observability/traces",
                    timeout_s=timeout_s,
                )
                summary = self.bindings._summarize_metrics(metrics)
                lines = [
                    f"status {health.get('status', 'unknown')}",
                    f"req {summary['requests_total']}",
                    f"err {summary['error_rate']:.2f}",
                    f"approvals {int(summary['pending_approvals'])}",
                ]
                if isinstance(spans, list) and spans:
                    lines.extend(self.bindings._render_span_tree(spans[-3:]))
                renderer.emit(renderer.detail_panel(self.command_id, lines))
                iterations += 1
                time.sleep(max(0.0, interval))
        except KeyboardInterrupt:
            session.update_step(0, "success")
        session.run_step(1, lambda: None)
        session.run_step(2, lambda: None)
        return {"iteration_count": iterations}


class _Worker(ArchonCommand):
    command_id = COMMAND_IDS[3]

    def run(self, session, *, config_path: str):  # type: ignore[no-untyped-def]
        runtime = session.run_step(0, _runtime_dir)
        session.run_step(1, _worker_db_path)
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
    command_id = COMMAND_IDS[4]

    def run(self, session):  # type: ignore[no-untyped-def]
        session.run_step(0, _runtime_dir)
        counts = session.run_step(1, _counts, _worker_db_path())
        lines = [f"{key} {value}" for key, value in counts.items()]
        session.run_step(2, lambda: None)
        session.print(renderer.detail_panel(self.command_id, lines))
        return counts


def build_group(bindings):
    @click.group(name=DRAWER_ID, invoke_without_command=True)
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("serve")
    @click.option("--host", default="127.0.0.1")
    @click.option("--port", default=8000, type=int)
    @click.option("--config", "config_path", default="config.archon.yaml")
    def serve_command(host: str, port: int, config_path: str) -> None:
        _Serve(bindings).invoke(host=host, port=port, config_path=config_path)

    @group.command("health")
    @click.option("--base-url", default="http://127.0.0.1:8000")
    @click.option("--timeout", "timeout_s", default=5.0, type=float)
    def health_command(base_url: str, timeout_s: float) -> None:
        _Health(bindings).invoke(base_url=base_url, timeout_s=timeout_s)

    @group.command("monitor")
    @click.option("--base-url", default="http://127.0.0.1:8000")
    @click.option("--timeout", "timeout_s", default=5.0, type=float)
    @click.option("--interval", default=5.0, type=float)
    def monitor_command(base_url: str, timeout_s: float, interval: float) -> None:
        _Monitor(bindings).invoke(base_url=base_url, timeout_s=timeout_s, interval=interval)

    @group.group("worker", invoke_without_command=True)
    @click.option("--config", "config_path", default="config.archon.yaml")
    @click.pass_context
    def worker_command(ctx: click.Context, config_path: str) -> None:
        if ctx.invoked_subcommand is None:
            _Worker(bindings).invoke(config_path=config_path)

    @worker_command.command("status")
    def worker_status_command() -> None:
        _WorkerStatus(bindings).invoke()

    return group
