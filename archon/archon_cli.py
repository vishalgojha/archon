"""ARCHON command line interface."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import click
import httpx
import yaml

from archon.api.auth import create_tenant_token
from archon.config import load_archon_config
from archon.core.orchestrator import Orchestrator
from archon.deploy.cli import deploy_group
from archon.federation.peer_discovery import Peer, PeerRegistry
from archon.memory.store import MemoryStore
from archon.redteam import RegressionRunner
from archon.validate_config import main as validate_config_main

try:  # pragma: no cover - optional dependency
    from rich.console import Console
    from rich.table import Table
except Exception:  # pragma: no cover - optional dependency
    Console = None
    Table = None

ARCHON_VERSION_FALLBACK = "0.1.0"
DEFAULT_CONFIG_PATH = "config.archon.yaml"
DEFAULT_SERVER_URL = "http://127.0.0.1:8000"


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


def _normalize_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip()
    if not normalized:
        return DEFAULT_SERVER_URL
    return normalized.rstrip("/")


def _create_api_headers(
    *,
    token: str | None = None,
    tenant_id: str = "default",
    tier: str = "pro",
) -> dict[str, str]:
    resolved = str(token or "").strip()
    if not resolved:
        resolved = create_tenant_token(tenant_id=tenant_id, tier=tier)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {resolved}"}


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout_s: float = 30.0,
) -> Any:
    response = httpx.request(
        method=method.upper(),
        url=url,
        headers=headers,
        json=json_body,
        timeout=timeout_s,
    )
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def _request_text(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_s: float = 30.0,
) -> str:
    response = httpx.request(
        method=method.upper(),
        url=url,
        headers=headers,
        timeout=timeout_s,
    )
    response.raise_for_status()
    return response.text


def _parse_context(
    context_text: str | None,
    context_file: Path | None,
) -> dict[str, Any]:
    if context_text and context_file is not None:
        raise click.ClickException("Use either --context or --context-file, not both.")
    if context_file is not None:
        with context_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    elif context_text:
        payload = json.loads(context_text)
    else:
        return {}
    if not isinstance(payload, dict):
        raise click.ClickException("Task context must decode to a JSON object.")
    return payload


def _launch_url(url: str) -> None:
    if not click.launch(url):
        raise click.ClickException(f"Could not open browser for {url}")


def _run_api_server_with_env(*, host: str, port: int) -> None:
    previous_host = os.environ.get("ARCHON_HOST")
    previous_port = os.environ.get("ARCHON_PORT")
    os.environ["ARCHON_HOST"] = host
    os.environ["ARCHON_PORT"] = str(port)
    try:
        from archon.interfaces.api.server import run as run_api_server

        run_api_server()
    finally:
        if previous_host is None:
            os.environ.pop("ARCHON_HOST", None)
        else:
            os.environ["ARCHON_HOST"] = previous_host
        if previous_port is None:
            os.environ.pop("ARCHON_PORT", None)
        else:
            os.environ["ARCHON_PORT"] = previous_port


def _parse_prometheus_text(text: str) -> dict[str, list[dict[str, Any]]]:
    metrics: dict[str, list[dict[str, Any]]] = {}
    label_pattern = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"])*)"')
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        sample, _, value_blob = line.rpartition(" ")
        if not sample or not value_blob:
            continue
        try:
            value = float(value_blob)
        except ValueError:
            continue
        labels: dict[str, str] = {}
        if "{" in sample and sample.endswith("}"):
            name, labels_blob = sample[:-1].split("{", 1)
            for key, raw_value in label_pattern.findall(labels_blob):
                labels[key] = raw_value.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
        else:
            name = sample
        metrics.setdefault(name, []).append({"labels": labels, "value": value})
    return metrics


def _metric_total(
    metrics: dict[str, list[dict[str, Any]]],
    metric_name: str,
    *,
    predicate: Any = None,
) -> float:
    total = 0.0
    for sample in metrics.get(metric_name, []):
        labels = sample.get("labels", {})
        if callable(predicate) and not predicate(labels):
            continue
        total += float(sample.get("value", 0.0) or 0.0)
    return total


def _metric_gauge(metrics: dict[str, list[dict[str, Any]]], metric_name: str) -> float:
    samples = metrics.get(metric_name, [])
    if not samples:
        return 0.0
    return float(samples[-1].get("value", 0.0) or 0.0)


def _top_provider(metrics: dict[str, list[dict[str, Any]]]) -> str:
    totals: dict[str, float] = {}
    for sample in metrics.get("archon_llm_calls_total", []):
        labels = sample.get("labels", {})
        provider = str(labels.get("provider", "unknown"))
        totals[provider] = totals.get(provider, 0.0) + float(sample.get("value", 0.0) or 0.0)
    if not totals:
        return "none"
    provider, count = max(totals.items(), key=lambda item: item[1])
    return f"{provider} ({int(count)})"


def _top_agents(metrics: dict[str, list[dict[str, Any]]], *, limit: int = 3) -> list[str]:
    rows: list[tuple[str, float]] = []
    for sample in metrics.get("archon_agents_recruited_total", []):
        labels = sample.get("labels", {})
        rows.append((str(labels.get("agent_name", "unknown")), float(sample.get("value", 0.0) or 0.0)))
    rows.sort(key=lambda item: item[1], reverse=True)
    return [f"{name} ({int(count)})" for name, count in rows[: max(1, int(limit))]]


def _summarize_metrics(text: str) -> dict[str, Any]:
    metrics = _parse_prometheus_text(text)
    total_requests = _metric_total(metrics, "archon_requests_total")
    error_requests = _metric_total(
        metrics,
        "archon_requests_total",
        predicate=lambda labels: str(labels.get("status", "")).startswith("5"),
    )
    error_rate = (error_requests / total_requests * 100.0) if total_requests else 0.0
    return {
        "metrics": metrics,
        "requests_total": total_requests,
        "error_rate": error_rate,
        "active_sessions": _metric_gauge(metrics, "archon_active_sessions"),
        "pending_approvals": _metric_gauge(metrics, "archon_pending_approvals"),
        "top_provider": _top_provider(metrics),
        "top_agents": _top_agents(metrics),
    }


def _render_span_tree(spans: list[dict[str, Any]]) -> list[str]:
    if not spans:
        return ["No spans."]

    by_id = {str(span.get("span_id", "")): span for span in spans}
    children: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []
    for span in spans:
        parent_id = str(span.get("parent_id") or "")
        if parent_id and parent_id in by_id:
            children.setdefault(parent_id, []).append(span)
        else:
            roots.append(span)

    lines: list[str] = []

    def walk(node: dict[str, Any], depth: int) -> None:
        status = str(node.get("status", "ok"))
        name = str(node.get("name", "span"))
        duration = float(node.get("duration_ms", 0.0) or 0.0)
        suffix = ""
        if status != "ok":
            error = str(node.get("error", "")).strip()
            suffix = f" error={error}" if error else " error"
        lines.append(f"{'  ' * depth}- {name} [{status}] {duration:.1f}ms{suffix}")
        for child in children.get(str(node.get("span_id", "")), []):
            walk(child, depth + 1)

    for root in roots:
        walk(root, 0)
    return lines


def _monitor_sleep(seconds: float) -> None:
    time.sleep(max(0.0, float(seconds)))


def _clear_monitor_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


@click.group()
def cli() -> None:
    """ARCHON CLI."""


cli.add_command(deploy_group)


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


@cli.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def serve_command(host: str, port: int, config_path: str) -> None:
    """Start the ARCHON API server."""

    _load_config(config_path)
    try:
        _run_api_server_with_env(host=host, port=port)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc


@cli.command("health")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
@click.option("--timeout", "timeout_s", default=5.0, show_default=True, type=float)
def health_command(base_url: str, timeout_s: float) -> None:
    """Check health of a running ARCHON server."""

    printer = _Printer()
    url = f"{_normalize_base_url(base_url)}/health"
    try:
        payload = _request_json("GET", url, timeout_s=timeout_s)
    except (httpx.HTTPError, ValueError) as exc:
        raise click.ClickException(f"Health check failed: {exc}") from exc

    status = str(payload.get("status", "unknown"))
    version = str(payload.get("version", "unknown"))
    db_status = str(payload.get("db_status", "unknown"))
    uptime_s = float(payload.get("uptime_s", 0.0) or 0.0)
    printer.print(f"Status: {status}")
    printer.print(f"Version: {version}")
    printer.print(f"DB: {db_status}")
    printer.print(f"Uptime: {uptime_s:.2f}s")


@cli.command("metrics")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
@click.option("--timeout", "timeout_s", default=5.0, show_default=True, type=float)
@click.option("--raw", is_flag=True, default=False)
def metrics_command(base_url: str, timeout_s: float, raw: bool) -> None:
    """Fetch and summarize ARCHON metrics."""

    url = f"{_normalize_base_url(base_url)}/metrics"
    try:
        payload = _request_text("GET", url, timeout_s=timeout_s)
    except httpx.HTTPError as exc:
        raise click.ClickException(f"Metrics request failed: {exc}") from exc
    if raw:
        click.echo(payload, nl=False)
        return

    printer = _Printer()
    summary = _summarize_metrics(payload)
    printer.table(
        ["metric", "value"],
        [
            ["requests_total", int(summary["requests_total"])],
            ["error_rate", f"{summary['error_rate']:.2f}%"],
            ["active_sessions", int(summary["active_sessions"])],
            ["pending_approvals", int(summary["pending_approvals"])],
            ["top_provider", summary["top_provider"]],
        ],
    )


@cli.command("traces")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
@click.option("--timeout", "timeout_s", default=5.0, show_default=True, type=float)
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--failed", is_flag=True, default=False)
def traces_command(base_url: str, timeout_s: float, limit: int, failed: bool) -> None:
    """Fetch and render recent ARCHON spans."""

    url = f"{_normalize_base_url(base_url)}/observability/traces"
    try:
        spans = _request_json(
            "GET",
            url,
            json_body=None,
            timeout_s=timeout_s,
            headers=None,
        )
    except httpx.HTTPError as exc:
        raise click.ClickException(f"Traces request failed: {exc}") from exc

    if not isinstance(spans, list):
        raise click.ClickException("Unexpected traces payload.")
    filtered = [span for span in spans if not failed or str(span.get("status", "ok")) != "ok"]
    limited = filtered[-max(1, int(limit)) :]
    for line in _render_span_tree(limited):
        click.echo(line)


@cli.command("monitor")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
@click.option("--timeout", "timeout_s", default=5.0, show_default=True, type=float)
@click.option("--interval", default=5.0, show_default=True, type=float)
def monitor_command(base_url: str, timeout_s: float, interval: float) -> None:
    """Render a live terminal monitor for ARCHON."""

    printer = _Printer()
    normalized_base = _normalize_base_url(base_url)
    previous_total: float | None = None
    previous_ts: float | None = None
    try:
        while True:
            health = _request_json("GET", f"{normalized_base}/health", timeout_s=timeout_s)
            metrics_text = _request_text("GET", f"{normalized_base}/metrics", timeout_s=timeout_s)
            spans = _request_json(
                "GET",
                f"{normalized_base}/observability/traces",
                timeout_s=timeout_s,
            )
            summary = _summarize_metrics(metrics_text)
            now = time.monotonic()
            req_per_s = 0.0
            if previous_total is not None and previous_ts is not None and now > previous_ts:
                req_per_s = max(0.0, (summary["requests_total"] - previous_total) / (now - previous_ts))
            previous_total = float(summary["requests_total"])
            previous_ts = now
            _clear_monitor_screen()
            status = "ok" if str(health.get("status", "unknown")) == "ok" else "down"
            printer.print(f"ARCHON monitor status={status}")
            printer.print(f"req/s: {req_per_s:.2f}")
            printer.print(f"error%: {summary['error_rate']:.2f}")
            printer.print(f"active_sessions: {int(summary['active_sessions'])}")
            printer.print(f"pending_approvals: {int(summary['pending_approvals'])}")
            printer.print("top_agents: " + (", ".join(summary["top_agents"]) if summary["top_agents"] else "none"))
            printer.print("last_spans:")
            rendered = _render_span_tree(list(spans)[-5:] if isinstance(spans, list) else [])
            for line in rendered:
                printer.print(line)
            _monitor_sleep(interval)
    except KeyboardInterrupt:
        printer.print("Monitor stopped.")


@cli.command("task")
@click.argument("goal")
@click.option("--mode", type=click.Choice(["debate", "growth", "auto"]), default="auto")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
@click.option("--tenant-id", default="default", show_default=True)
@click.option("--tier", type=click.Choice(["free", "pro", "enterprise"]), default="pro", show_default=True)
@click.option("--token", default="", show_default=False)
@click.option("--context", "context_text", default="", show_default=False)
@click.option(
    "--context-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
@click.option("--timeout", "timeout_s", default=60.0, show_default=True, type=float)
def task_command(
    goal: str,
    mode: str,
    base_url: str,
    tenant_id: str,
    tier: str,
    token: str,
    context_text: str,
    context_file: Path | None,
    timeout_s: float,
) -> None:
    """Send one task to the running ARCHON API."""

    printer = _Printer()
    effective_mode = _resolve_mode(mode, goal)
    context = _parse_context(context_text or None, context_file)
    headers = _create_api_headers(token=token or None, tenant_id=tenant_id, tier=tier)
    url = f"{_normalize_base_url(base_url)}/v1/tasks"
    body = {
        "goal": goal,
        "mode": effective_mode,
        "context": context,
    }
    try:
        payload = _request_json(
            "POST",
            url,
            headers=headers,
            json_body=body,
            timeout_s=timeout_s,
        )
    except (httpx.HTTPError, ValueError) as exc:
        raise click.ClickException(f"Task request failed: {exc}") from exc

    printer.print(f"[bold]Mode:[/bold] {payload.get('mode', effective_mode)}")
    printer.print(str(payload.get("final_answer", "")))
    printer.print(f"Confidence: {int(payload.get('confidence', 0) or 0)}%")
    budget = payload.get("budget") or {}
    printer.print(f"Budget spent: ${float(budget.get('spent_usd', 0.0) or 0.0):.4f}")


@cli.command("dashboard")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
def dashboard_command(base_url: str) -> None:
    """Open the Mission Control dashboard in the default browser."""

    _launch_url(f"{_normalize_base_url(base_url)}/dashboard")


@cli.command("studio")
@click.option("--base-url", default=DEFAULT_SERVER_URL, show_default=True)
def studio_command(base_url: str) -> None:
    """Open ARCHON Studio in the default browser."""

    _launch_url(f"{_normalize_base_url(base_url)}/studio")


@cli.command("debate")
@click.argument("question")
@click.option("--mode", type=click.Choice(["debate", "growth", "auto"]), default="auto")
@click.option("--budget", type=float, default=None)
@click.option("--live-providers", is_flag=True, default=False)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def debate_command(
    question: str,
    mode: str,
    budget: float | None,
    live_providers: bool,
    config_path: str,
) -> None:
    """Run ARCHON debate/growth orchestration for a question."""

    printer = _Printer()
    config = _load_config(config_path)
    if budget is not None:
        config.byok.budget_per_task_usd = float(budget)
    effective_mode = _resolve_mode(mode, question)

    async def _run() -> None:
        orchestrator = Orchestrator(config=config, live_provider_calls=live_providers)
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
@click.option("--live-providers", is_flag=True, default=False)
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
def run_command(workflow_file: Path, dry_run: bool, live_providers: bool, config_path: str) -> None:
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
        orchestrator = Orchestrator(config=config, live_provider_calls=live_providers)
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


@cli.group("redteam")
def redteam_group() -> None:
    """Automated red-team regression operations."""


@redteam_group.command("regression")
@click.option("--config", "config_path", default=DEFAULT_CONFIG_PATH, show_default=True)
@click.option(
    "--output-dir",
    default="artifacts/redteam",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--payloads-per-vector", default=1, show_default=True, type=int)
@click.option("--live-providers", is_flag=True, default=False)
def redteam_regression_command(
    config_path: str,
    output_dir: Path,
    payloads_per_vector: int,
    live_providers: bool,
) -> None:
    """Run a deterministic red-team regression sweep and export artifacts."""

    outcome = asyncio.run(
        _run_redteam_regression(
            config_path=config_path,
            output_dir=output_dir,
            payloads_per_vector=payloads_per_vector,
            live_provider_calls=live_providers,
        )
    )
    printer = _Printer()
    printer.print(f"Regression scan: {outcome.report.scan_id}")
    printer.print(f"Payloads: {outcome.report.total_payloads}")
    printer.print(f"Findings: {len(outcome.report.findings)}")
    printer.print(f"Markdown report: {outcome.markdown_path}")
    printer.print(f"JSON report: {outcome.json_path}")
    if outcome.failed_categories:
        printer.print(
            "Failed categories: "
            + ", ".join(
                f"{category}={value:.3f}" for category, value in sorted(outcome.failed_categories.items())
            )
        )
    if outcome.blocking_findings:
        printer.print(
            "Blocking findings: "
            + ", ".join(
                f"{finding.agent_name}:{finding.failure_mode}:{finding.severity}"
                for finding in outcome.blocking_findings
            )
        )
    if not outcome.passed:
        raise click.ClickException("Red-team regression failed.")


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


async def _run_redteam_regression(
    *,
    config_path: str,
    output_dir: Path,
    payloads_per_vector: int,
    live_provider_calls: bool,
):
    config = _load_config(config_path)
    orchestrator = Orchestrator(config=config, live_provider_calls=live_provider_calls)
    try:
        runner = RegressionRunner(orchestrator=orchestrator)
        return await runner.run(
            output_dir=output_dir,
            payloads_per_vector=payloads_per_vector,
        )
    finally:
        await orchestrator.aclose()


def main() -> None:
    """Entry point for `python -m archon.archon_cli`."""

    cli(prog_name="archon")


if __name__ == "__main__":
    main()
