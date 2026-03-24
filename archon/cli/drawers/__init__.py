from __future__ import annotations

from importlib import import_module
from pkgutil import iter_modules
from types import ModuleType


def _discover_drawer_modules() -> tuple[ModuleType, ...]:
    module_names = []
    for module_info in iter_modules(__path__, prefix=f"{__name__}."):
        name = module_info.name.rsplit(".", 1)[-1]
        if name == "__init__" or name.startswith("_"):
            continue
        module_names.append(module_info.name)
    return tuple(import_module(module_name) for module_name in sorted(module_names))


DRAWER_MODULES = _discover_drawer_modules()


def get_drawer_modules() -> tuple[ModuleType, ...]:
    return DRAWER_MODULES


__all__ = ["DRAWER_MODULES", "get_drawer_modules"]
