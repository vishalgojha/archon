from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

import click

from archon.cli import renderer
from archon.cli.copy import DRAWER_COPY


@dataclass(frozen=True)
class _DrawerSpec:
    drawer_id: str
    module_path: str


class _LazyDrawerModule:
    __slots__ = ("_spec", "_module")

    def __init__(self, spec: _DrawerSpec) -> None:
        self._spec = spec
        self._module = None

    @property
    def __file__(self) -> str:
        return str(_module_file_path(self._spec.module_path))

    def _load(self) -> Any:
        if self._module is None:
            self._module = import_module(self._spec.module_path)
        return self._module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)


def _module_file_path(module_path: str) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / Path(*module_path.split(".")).with_suffix(".py")


DRAWER_SPECS = (
    _DrawerSpec("core", "archon.cli.drawers.core"),
    _DrawerSpec("agents", "archon.cli.drawers.agents"),
    _DrawerSpec("growth", "archon.cli.drawers.growth"),
    _DrawerSpec("vision", "archon.cli.drawers.vision"),
    _DrawerSpec("web", "archon.cli.drawers.web"),
    _DrawerSpec("memory", "archon.cli.drawers.memory"),
    _DrawerSpec("evolve", "archon.cli.drawers.evolve"),
    _DrawerSpec("federation", "archon.cli.drawers.federation"),
    _DrawerSpec("providers", "archon.cli.drawers.providers"),
    _DrawerSpec("marketplace", "archon.cli.drawers.marketplace"),
    _DrawerSpec("studio", "archon.cli.drawers.studio"),
    _DrawerSpec("ops", "archon.cli.drawers.ops"),
)

DRAWER_MODULES = tuple(_LazyDrawerModule(spec) for spec in DRAWER_SPECS)
REGISTERED_DRAWERS = tuple(spec.drawer_id for spec in DRAWER_SPECS)
REGISTERED_COMMANDS = tuple(
    command_id
    for drawer_id in REGISTERED_DRAWERS
    for command_id in DRAWER_COPY[drawer_id]["commands"]
)


def _show_root() -> None:
    renderer.emit(renderer.banner())
    for drawer_id in REGISTERED_DRAWERS:
        renderer.emit(renderer.drawer_panel(drawer_id))


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
