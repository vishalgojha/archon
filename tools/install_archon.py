"""Global installer for a checked-out ARCHON repository."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_INSTALLER_PATH = _REPO_ROOT / "archon" / "runtime_installer.py"

_SPEC = importlib.util.spec_from_file_location(
    "archon_runtime_installer_bootstrap", _RUNTIME_INSTALLER_PATH
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Could not load runtime installer from {_RUNTIME_INSTALLER_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

default_install_root = _MODULE.default_install_root
install = _MODULE.install
load_dependency_specs = _MODULE.load_dependency_specs
main = _MODULE.main
merge_path_value = _MODULE.merge_path_value
remove_path_value = _MODULE.remove_path_value
render_posix_shim = _MODULE.render_posix_shim
render_windows_cmd_shim = _MODULE.render_windows_cmd_shim
render_windows_ps1_shim = _MODULE.render_windows_ps1_shim
resolve_command_path = _MODULE.resolve_command_path
uninstall = _MODULE.uninstall

__all__ = [
    "default_install_root",
    "install",
    "load_dependency_specs",
    "main",
    "merge_path_value",
    "remove_path_value",
    "render_posix_shim",
    "render_windows_cmd_shim",
    "render_windows_ps1_shim",
    "resolve_command_path",
    "uninstall",
]


if __name__ == "__main__":
    raise SystemExit(main())
