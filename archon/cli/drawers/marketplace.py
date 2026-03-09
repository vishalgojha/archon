from __future__ import annotations

import click

from archon.cli import renderer
from archon.cli.base_command import PlaceholderCommand
from archon.cli.copy import DRAWER_COPY

DRAWER_ID = "marketplace"
COMMAND_IDS = ("marketplace.payouts", "marketplace.earnings")
DRAWER_META = DRAWER_COPY[DRAWER_ID]
COMMAND_HELP = DRAWER_META["commands"]


class _Payouts(PlaceholderCommand):
    command_id = COMMAND_IDS[0]


class _Earnings(PlaceholderCommand):
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

    @group.command("payouts", help=str(COMMAND_HELP[COMMAND_IDS[0]]))
    def payouts_command() -> None:
        _Payouts(bindings).invoke()

    @group.command("earnings", help=str(COMMAND_HELP[COMMAND_IDS[1]]))
    def earnings_command() -> None:
        _Earnings(bindings).invoke()

    return group
