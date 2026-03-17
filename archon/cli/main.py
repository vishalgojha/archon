from __future__ import annotations

from typing import Any

import click

from archon.cli import renderer
from archon.cli.registry import get_drawers


def build_cli(bindings: Any) -> click.Group:
    drawers = get_drawers()

    @click.group(invoke_without_command=True)
    @click.pass_context
    def app(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is not None:
            return
        renderer.emit(renderer.banner())
        for drawer in drawers:
            renderer.emit(renderer.drawer_panel(drawer.drawer_id))

    drawer_groups = {drawer.drawer_id: drawer.build_group(bindings) for drawer in drawers}
    for drawer_id, group in drawer_groups.items():
        app.add_command(group, drawer_id)

    core_group = drawer_groups.get("core")
    if core_group is not None:
        init_alias = core_group.commands.get("init")
        if init_alias is not None:
            app.add_command(init_alias, "init")
        studio_alias = core_group.commands.get("studio")
        if studio_alias is not None:
            app.add_command(studio_alias, "studio")

    legacy = getattr(bindings, "legacy_cli", None)
    if legacy is not None:
        for name, command in legacy.commands.items():
            if name in drawer_groups:
                continue
            app.add_command(command, name)

    return app
