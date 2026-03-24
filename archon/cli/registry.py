from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable

import click

from archon.cli.copy import DRAWER_COPY
from archon.cli.drawers import get_drawer_modules

DrawerBuilder = Callable[[Any], click.Group]


@dataclass(frozen=True, slots=True)
class DrawerSpec:
    drawer_id: str
    module_path: str
    build_group: DrawerBuilder
    command_ids: tuple[str, ...]
    module: ModuleType

    @property
    def __file__(self) -> str:
        return str(getattr(self.module, "__file__", ""))


def _command_ids_for_module(module: ModuleType, drawer_id: str) -> tuple[str, ...]:
    raw_ids = getattr(module, "COMMAND_IDS", ())
    command_ids = tuple(str(item).strip() for item in raw_ids if str(item).strip())
    if command_ids:
        return command_ids
    commands = DRAWER_COPY.get(drawer_id, {}).get("commands", {})
    return tuple(str(command_id) for command_id in commands)


def _build_spec(module: ModuleType) -> DrawerSpec:
    drawer_id = str(getattr(module, "DRAWER_ID", "")).strip()
    if not drawer_id:
        raise ValueError(f"{module.__name__} must define DRAWER_ID")
    build_group = getattr(module, "build_group", None)
    if not callable(build_group):
        raise ValueError(f"{module.__name__} must define build_group(bindings)")
    return DrawerSpec(
        drawer_id=drawer_id,
        module_path=str(module.__name__),
        build_group=build_group,
        command_ids=_command_ids_for_module(module, drawer_id),
        module=module,
    )


def get_drawers() -> list[DrawerSpec]:
    drawers = sorted(
        (_build_spec(module) for module in get_drawer_modules()), key=lambda item: item.drawer_id
    )
    seen: set[str] = set()
    duplicates: list[str] = []
    for drawer in drawers:
        if drawer.drawer_id in seen:
            duplicates.append(drawer.drawer_id)
            continue
        seen.add(drawer.drawer_id)
    if duplicates:
        duplicate_ids = ", ".join(sorted(set(duplicates)))
        raise ValueError(f"Duplicate CLI drawer ids discovered: {duplicate_ids}")
    return drawers


REGISTERED_DRAWERS = tuple(drawer.drawer_id for drawer in get_drawers())
REGISTERED_COMMANDS = tuple(
    command_id for drawer in get_drawers() for command_id in drawer.command_ids
)
DRAWER_MODULES = tuple(drawer.module for drawer in get_drawers())
