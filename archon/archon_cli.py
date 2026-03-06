"""ARCHON command line interface."""

from __future__ import annotations

import asyncio
import importlib.metadata
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import click
import yaml

from archon.api.auth import create_tenant_token
from archon.config import load_archon_config
from archon.core.orchestrator import Orchestrator
from archon.federation.peer_discovery import Peer, PeerRegistry
from archon.memory.store import MemoryStore
from archon.validate_config import main as validate_config_main

try:  # pragma: no cover - optional dependency
    from rich.console import Console
    from rich.table import Table
except Exception:  # pragma: no cover - optional dependency
    Console = None
    Table = None

ARCHON_VERSION_FALLBACK = "0.1.0"
DEFAULT_CONFIG_PATH = "config.archon.yaml"


class _Printer:
    def __init__(self) -> None:
        self._console = Console() if Console is not None else None

    def print(self, message: str) -> None:
        if self._console is not None:
            self._console.print(message)
        else:
            click.echo(message)

    def table(self, columns: list[str], rows: list[list[Any]]) -> None:
        if self._console is not None and Table is not None:
            table = Table(show_header=True, header_style="bold cyan")
            for column in columns:
                table.add_column(column)
            for row in rows:
                table.add_row(*[str(item) for item in row])
            self._console.print(table)
            return

        if not rows:
            self.print(" | ".join(columns))
            return
        widths = [len(column) for column in columns]
        for row in rows:
            for idx, value in enumerate(row):
                widths[idx] = max(widths[idx], len(str(value)))
        header = " | ".join(column.ljust(widths[idx]) for idx, column in enumerate(columns))
        self.print(header)
        self.print("-+-".join("-" * width for width in widths))
        for row in rows:
            self.print(" | ".join(str(value).ljust(widths[idx]) for idx, value in enumerate(row)))


def _load_config(path: str = DEFAULT_CONFIG_PATH):
    return load_archon_config(path)


def _resolve_mode(mode: str, prompt: str) -> str:
    if mode != "auto":
        return mode
    lowered = prompt.lower()
    growth_hints = ("lead", "pipeline", "outreach", "growth", "revenue", "churn", "prospect")
    return "growth" if any(hint in lowered for hint in growth_hints) else "debate"


def _resolve_version() -> str:
    try:
        return importlib.metadata.version("archon")
    except Exception:
        return ARCHON_VERSION_FALLBACK


def _resolve_git_sha() -> str:
    try:
        repo_root = Path(__file__).resolve().parents[1]
        value = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return value.strip() or "unknown"
    except Exception:
        return "unknown"


@click.group()
def cli() -> None:
    """ARCHON CLI."""


@cli.command("validate")
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
@click.option("--dry-run", is_flag=True, default=False)
def validate_command(config_path: str, dry_run: bool) -> None:
    """Runs validate_config."""

    _load_config(config_path)
    args = ["--config", config_path]
    if dry_run:
        args.append("--dry-run")
    exit_code = int(validate_config_main(args))
    raise click.exceptions.Exit(exit_code)


@cli.command("debate")
@click.argument("question")
@click.option("--mode", type=click.Choice(["debate", "growth", "auto"]), default="auto")
@click.option("--budget", type=float, default=None)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def debate_command(question: str, mode: str, budget: float | None, config_path: str) -> None:
    """Run ARCHON debate/growth orchestration for a question."""

    printer = _Printer()
    config = _load_config(config_path)
    if budget is not None:
        config.byok.budget_per_task_usd = float(budget)
    effective_mode = _resolve_mode(mode, question)

    async def _run() -> None:
        orchestrator = Orchestrator(config=config, live_provider_calls=False)
        try:
            result = await orchestrator.execute(goal=question, mode=effective_mode)  # type: ignore[arg-type]
            printer.print(f"[bold]Mode:[/bold] {result.mode}")
            printer.print(result.final_answer)
            printer.print(f"Confidence: {result.confidence}%")
            printer.print(f"Budget spent: ${result.budget.get('spent_usd', 0):.4f}")
        finally:
            await orchestrator.aclose()

    asyncio.run(_run())


@cli.command("run")
@click.argument("workflow_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def run_command(workflow_file: Path, dry_run: bool, config_path: str) -> None:
    """Run workflow YAML."""

    printer = _Printer()
    config = _load_config(config_path)
    with workflow_file.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise click.ClickException("Workflow file must contain a YAML object.")

    if dry_run:
        name = str(payload.get("name", workflow_file.name))
        steps = payload.get("steps", [])
        printer.print(f"Dry-run workflow: {name}")
        printer.print(f"Steps: {len(steps) if isinstance(steps, list) else 0}")
        return

    goal = str(payload.get("goal", f"Run workflow from {workflow_file.name}"))
    mode = str(payload.get("mode", "debate")).lower()
    if mode not in {"debate", "growth"}:
        mode = "debate"

    async def _run() -> None:
        orchestrator = Orchestrator(config=config, live_provider_calls=False)
        try:
            result = await orchestrator.execute(goal=goal, mode=mode)  # type: ignore[arg-type]
            printer.print(result.final_answer)
        finally:
            await orchestrator.aclose()

    asyncio.run(_run())


@cli.group("memory")
def memory_group() -> None:
    """Memory operations."""


@memory_group.command("search")
@click.argument("query")
@click.option("--tenant", "tenant_id", default="default", show_default=True)
@click.option("--top-k", default=10, show_default=True, type=int)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def memory_search_command(query: str, tenant_id: str, top_k: int, config_path: str) -> None:
    """Search memory."""

    _load_config(config_path)
    store = MemoryStore()
    printer = _Printer()
    try:
        results = store.search(query=query, tenant_id=tenant_id, top_k=top_k)
    finally:
        store.close()

    rows = []
    for row in results:
        rows.append(
            [
                row.memory.memory_id,
                f"{row.similarity:.3f}",
                row.memory.role,
                row.memory.content[:70],
            ]
        )
    if not rows:
        printer.print("No memory results.")
        return
    printer.table(["memory_id", "similarity", "role", "content"], rows)


@cli.group("peers")
def peers_group() -> None:
    """Federation peer operations."""


@peers_group.command("list")
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def peers_list_command(config_path: str) -> None:
    """List known peers."""

    _load_config(config_path)
    printer = _Printer()

    async def _run() -> list[Peer]:
        registry = PeerRegistry()
        try:
            return await registry.discover(None)
        finally:
            await registry.aclose()

    peers = asyncio.run(_run())
    rows = [
        [peer.peer_id, peer.address, ",".join(peer.capabilities), peer.version] for peer in peers
    ]
    if not rows:
        printer.print("No peers found.")
        return
    printer.table(["peer_id", "address", "capabilities", "version"], rows)


@peers_group.command("add")
@click.argument("address")
@click.option("--capability", "capabilities", multiple=True)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def peers_add_command(address: str, capabilities: tuple[str, ...], config_path: str) -> None:
    """Add one peer."""

    _load_config(config_path)
    printer = _Printer()
    now = time.time()
    peer = Peer(
        peer_id=f"peer-{uuid.uuid4().hex[:8]}",
        address=address,
        public_key="unknown",
        last_seen=now,
        capabilities=list(capabilities) if capabilities else ["debate"],
        version="unknown",
    )

    async def _run() -> Peer:
        registry = PeerRegistry()
        try:
            return await registry.register(peer)
        finally:
            await registry.aclose()

    registered = asyncio.run(_run())
    printer.print(f"Peer added: {registered.peer_id} @ {registered.address}")


@cli.group("token")
def token_group() -> None:
    """Tenant token operations."""


@token_group.command("create")
@click.option("--tenant-id", required=True)
@click.option("--tier", type=click.Choice(["free", "pro", "enterprise"]), required=True)
@click.option("--expires-in", default=3600, show_default=True, type=int)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def token_create_command(tenant_id: str, tier: str, expires_in: int, config_path: str) -> None:
    """Create signed tenant JWT."""

    _load_config(config_path)
    token = create_tenant_token(tenant_id=tenant_id, tier=tier, expires_in_seconds=expires_in)  # type: ignore[arg-type]
    click.echo(token)


@cli.command("version")
def version_command() -> None:
    """Print ARCHON version + git sha."""

    click.echo(f"ARCHON {_resolve_version()} (git {_resolve_git_sha()})")


def main() -> None:
    """Entry point for `python -m archon.archon_cli`."""

    cli(prog_name="archon")


if __name__ == "__main__":
    main()
