from __future__ import annotations

import click

from archon.cli import renderer
from archon.cli.base_command import PlaceholderCommand

DRAWER_ID = "federation"
COMMAND_IDS = ("federation.peers", "federation.sync")


class _Peers(PlaceholderCommand):
    command_id = COMMAND_IDS[0]


class _Sync(PlaceholderCommand):
    command_id = COMMAND_IDS[1]


def build_group(bindings):
    @click.group(name=DRAWER_ID, invoke_without_command=True)
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("peers")
    def peers_command() -> None:
        _Peers(bindings).invoke()

    @group.command("sync")
    def sync_command() -> None:
        _Sync(bindings).invoke()

    return group
