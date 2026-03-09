from __future__ import annotations

import click

from archon.cli.base_command import PlaceholderCommand
from archon.cli import renderer

DRAWER_ID = "marketplace"
COMMAND_IDS = ("marketplace.payouts", "marketplace.earnings")


class _Payouts(PlaceholderCommand):
    command_id = COMMAND_IDS[0]


class _Earnings(PlaceholderCommand):
    command_id = COMMAND_IDS[1]


def build_group(bindings):
    @click.group(name=DRAWER_ID, invoke_without_command=True)
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("payouts")
    def payouts_command() -> None:
        _Payouts(bindings).invoke()

    @group.command("earnings")
    def earnings_command() -> None:
        _Earnings(bindings).invoke()

    return group
