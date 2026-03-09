from __future__ import annotations

import click

from archon.cli import renderer
from archon.cli.base_command import PlaceholderCommand
from archon.cli.copy import DRAWER_COPY

DRAWER_ID = "web"
COMMAND_IDS = ("web.crawl", "web.optimize")
DRAWER_META = DRAWER_COPY[DRAWER_ID]
COMMAND_HELP = DRAWER_META["commands"]


class _Crawl(PlaceholderCommand):
    command_id = COMMAND_IDS[0]


class _Optimize(PlaceholderCommand):
    command_id = COMMAND_IDS[1]


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

    @group.command("crawl", help=str(COMMAND_HELP[COMMAND_IDS[0]]))
    def crawl_command() -> None:
        _Crawl(bindings).invoke()

    @group.command("optimize", help=str(COMMAND_HELP[COMMAND_IDS[1]]))
    def optimize_command() -> None:
        _Optimize(bindings).invoke()

    return group
