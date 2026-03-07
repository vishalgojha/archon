"""Focused tests for the repo-level global installer helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _installer_module():
    module_path = _repo_root() / "tools" / "install_archon.py"
    spec = importlib.util.spec_from_file_location("archon_install_archon", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_dependency_specs_includes_base_only_by_default() -> None:
    deps = _installer_module().load_dependency_specs(_repo_root() / "pyproject.toml")

    assert "click>=8.1.7" in deps
    assert "pytest>=8.2.0" not in deps


def test_load_dependency_specs_can_include_dev_without_duplicates() -> None:
    deps = _installer_module().load_dependency_specs(
        _repo_root() / "pyproject.toml", include_dev=True
    )

    assert "click>=8.1.7" in deps
    assert "pytest>=8.2.0" in deps
    assert deps.count("click>=8.1.7") == 1


def test_merge_path_value_appends_missing_entry_once() -> None:
    merged = _installer_module().merge_path_value(
        r"C:\Tools",
        Path(r"C:\Archon\bin"),
        platform_name="win32",
    )

    assert merged == r"C:\Tools;C:\Archon\bin"


def test_merge_path_value_is_case_insensitive_on_windows() -> None:
    existing = r"C:\Tools;C:\Users\Visha\AppData\Local\Programs\Archon\bin"
    merged = _installer_module().merge_path_value(
        existing,
        Path(r"c:\users\visha\appdata\local\programs\archon\bin"),
        platform_name="win32",
    )

    assert merged == existing


def test_render_windows_shims_target_repo_runtime() -> None:
    module = _installer_module()
    cmd = module.render_windows_cmd_shim("-m", "archon.archon_cli", "serve")
    ps1 = module.render_windows_ps1_shim("-m", "archon.archon_cli")

    assert '"%~dp0..\\venv\\Scripts\\python.exe" -m archon.archon_cli serve %*' in cmd
    assert '"$PSScriptRoot\\..\\venv\\Scripts\\python.exe" -m archon.archon_cli @args' in ps1


def test_default_install_root_uses_user_local_programs_on_windows(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\visha\AppData\Local")

    path = _installer_module().default_install_root("win32")

    assert path == Path(r"C:\Users\visha\AppData\Local\Programs\Archon")
