"""CLI group for deployment validation helpers."""

from __future__ import annotations

import click

from archon.deploy.validator import validate_all


@click.group("deploy")
def deploy_group() -> None:
    """Deployment operations."""


@deploy_group.command("validate")
@click.option("--root", default=".", show_default=True)
def validate_command(root: str) -> None:
    """Validate compose, observability, and Helm deployment assets."""

    report = validate_all(root)
    click.echo(f"compose ok: {report['compose']['ok']}")
    click.echo(f"observability ok: {report['observability']['ok']}")
    click.echo(f"otel ok: {report['otel']['ok']}")
    click.echo(f"helm ok: {report['helm']['ok']}")
    if report["compose"]["findings"]:
        for finding in report["compose"]["findings"]:
            click.echo(f"compose: {finding}")
    if report["observability"]["findings"]:
        for finding in report["observability"]["findings"]:
            click.echo(f"observability: {finding}")
    if report["otel"]["findings"]:
        for finding in report["otel"]["findings"]:
            click.echo(f"otel: {finding}")
    if report["helm"]["findings"]:
        for finding in report["helm"]["findings"]:
            click.echo(f"helm: {finding}")
    raise click.exceptions.Exit(0 if report["ok"] else 1)
