from __future__ import annotations

import click

from archon.cli import renderer
from archon.cli.base_command import PlaceholderCommand

DRAWER_ID = "web"
COMMAND_IDS = ("web.crawl", "web.optimize")


class _Crawl(PlaceholderCommand):
    command_id = COMMAND_IDS[0]


class _Optimize(PlaceholderCommand):
    command_id = COMMAND_IDS[1]


def build_group(bindings):
    @click.group(name=DRAWER_ID, invoke_without_command=True)
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("crawl")
    def crawl_command() -> None:
        _Crawl(bindings).invoke()

    @group.command("optimize")
    def optimize_command() -> None:
        _Optimize(bindings).invoke()

    return group

