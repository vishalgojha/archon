from __future__ import annotations

from typing import Any

import click

from archon.cli import renderer
from archon.cli.drawers import (
    agents,
    core,
    evolve,
    federation,
    growth,
    marketplace,
    memory,
    ops,
    providers,
    studio,
    vision,
    web,
)

DRAWER_MODULES = (
    core,
    agents,
    growth,
    vision,
    web,
    memory,
    evolve,
    federation,
    providers,
    marketplace,
    studio,
    ops,
)

REGISTERED_DRAWERS = tuple(module.DRAWER_ID for module in DRAWER_MODULES)
REGISTERED_COMMANDS = tuple(
    command_id
    for module in DRAWER_MODULES
    for command_id in getattr(module, "COMMAND_IDS", ())
)


def _show_root() -> None:
    renderer.emit(renderer.banner())
    for module in DRAWER_MODULES:
        renderer.emit(renderer.drawer_panel(module.DRAWER_ID))


def build_cli(bindings: Any) -> click.Group:
    @click.group(invoke_without_command=True)
    @click.pass_context
    def app(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            _show_root()

    drawer_groups = {module.DRAWER_ID: module.build_group(bindings) for module in DRAWER_MODULES}
    for name, group in drawer_groups.items():
        app.add_command(group, name)

    init_alias = drawer_groups["core"].commands.get("init")
    if init_alias is not None:
        app.add_command(init_alias, "init")

    legacy = getattr(bindings, "legacy_cli", None)
    if legacy is not None:
        for name, command in legacy.commands.items():
            if name in drawer_groups:
                continue
            if name == "studio":
                continue
            app.add_command(command, name)

    return app
