from __future__ import annotations

import time
from pathlib import Path

import click

from archon.cli.base_command import ArchonCommand
from archon.cli import renderer
from archon.providers.router import PROVIDER_ENV_KEY
from archon.validate_config import validate_config

DRAWER_ID = "providers"
COMMAND_IDS = ("providers.list", "providers.test")


def _roles(config) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    byok = config.byok
    rows = []
    for role in ("primary", "coding", "vision", "fast", "embedding", "fallback"):
        value = str(getattr(byok, role, "") or "").strip()
        if value:
            rows.append((role, value))
    return rows


class _List(ArchonCommand):
    command_id = COMMAND_IDS[0]

    def run(self, session, *, config_path: str):  # type: ignore[no-untyped-def]
        config = session.run_step(0, self.bindings._load_config, config_path)
        rows = session.run_step(1, _roles, config)
        lines = []
        count = 0
        for role, provider in rows:
            env_name = PROVIDER_ENV_KEY.get(provider, "")
            present = bool(
                str(
                    self.bindings.os.getenv(env_name)
                    or self.bindings._read_env_value(env_name)
                    or ""
                ).strip()
            )
            count += 1
            lines.append(f"{role} {provider} key={'yes' if present else 'no'}")
        session.run_step(2, lambda: None)
        session.run_step(3, lambda: None)
        session.print(renderer.detail_panel(self.command_id, lines))
        return {"provider_count": count}


class _Test(ArchonCommand):
    command_id = COMMAND_IDS[1]

    def run(self, session, *, config_path: str, timeout_s: float):  # type: ignore[no-untyped-def]
        config = session.run_step(0, self.bindings._load_config, config_path)
        providers = sorted({provider for _, provider in _roles(config)})
        results = []
        pass_count = 0
        for provider in providers:
            started = time.perf_counter()
            report = session.run_step(
                1,
                validate_config,
                config_path,
                provider=provider,
                timeout_seconds=timeout_s,
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            health = next(
                (item for item in report.provider_health if item.provider == provider),
                None,
            )
            status = getattr(health, "status", "FAIL")
            if status == "PASS":
                pass_count += 1
            detail = getattr(health, "detail", "")
            results.append(f"{provider} {status} {latency_ms:.1f}ms {detail}".strip())
        session.run_step(2, lambda: None)
        session.run_step(3, lambda: None)
        session.print(renderer.detail_panel(self.command_id, results))
        return {"provider_count": len(providers), "pass_count": pass_count}


def build_group(bindings):
    @click.group(name=DRAWER_ID, invoke_without_command=True)
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("list")
    @click.option("--config", "config_path", default="config.archon.yaml")
    def list_command(config_path: str) -> None:
        _List(bindings).invoke(config_path=config_path)

    @group.command("test")
    @click.option("--config", "config_path", default="config.archon.yaml")
    @click.option("--timeout", "timeout_s", default=6.0, type=float)
    def test_command(config_path: str, timeout_s: float) -> None:
        _Test(bindings).invoke(config_path=config_path, timeout_s=timeout_s)

    return group
