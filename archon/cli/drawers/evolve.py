from __future__ import annotations

import click

from archon.cli.base_command import PlaceholderCommand
from archon.cli import renderer

DRAWER_ID = "evolve"
COMMAND_IDS = ("evolve.plan", "evolve.apply")


class _Plan(PlaceholderCommand):
    command_id = COMMAND_IDS[0]


class _Apply(PlaceholderCommand):
    command_id = COMMAND_IDS[1]


def build_group(bindings):
    @click.group(name=DRAWER_ID, invoke_without_command=True)
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("plan")
    def plan_command() -> None:
        _Plan(bindings).invoke()

    @group.command("apply")
    def apply_command() -> None:
        _Apply(bindings).invoke()

    return group

