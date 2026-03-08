"""Global installer for a checked-out ARCHON repository."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from archon.runtime_installer import (  # noqa: E402
    default_install_root,
    install,
    load_dependency_specs,
    main,
    merge_path_value,
    remove_path_value,
    render_windows_cmd_shim,
    render_windows_ps1_shim,
    resolve_command_path,
    uninstall,
)

__all__ = [
    "default_install_root",
    "install",
    "load_dependency_specs",
    "main",
    "merge_path_value",
    "remove_path_value",
    "render_windows_cmd_shim",
    "render_windows_ps1_shim",
    "resolve_command_path",
    "uninstall",
]


if __name__ == "__main__":
    raise SystemExit(main())
