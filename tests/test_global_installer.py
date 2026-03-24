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


def test_merge_path_value_prioritizes_entry_when_requested() -> None:
    merged = _installer_module().merge_path_value(
        r"C:\Tools;C:\Python\Scripts",
        Path(r"C:\Archon\bin"),
        platform_name="win32",
        prioritize=True,
    )

    assert merged == r"C:\Archon\bin;C:\Tools;C:\Python\Scripts"


def test_merge_path_value_is_case_insensitive_on_windows() -> None:
    existing = r"C:\Tools;C:\Users\Visha\AppData\Local\Programs\Archon\bin"
    merged = _installer_module().merge_path_value(
        existing,
        Path(r"c:\users\visha\appdata\local\programs\archon\bin"),
        platform_name="win32",
    )

    assert merged == existing


def test_merge_path_value_repositions_existing_entry_when_prioritized() -> None:
    existing = r"C:\Python\Scripts;C:\Users\Visha\AppData\Local\Programs\Archon\bin;C:\Tools"
    merged = _installer_module().merge_path_value(
        existing,
        Path(r"c:\users\visha\appdata\local\programs\archon\bin"),
        platform_name="win32",
        prioritize=True,
    )

    assert merged == (
        r"c:\users\visha\appdata\local\programs\archon\bin;C:\Python\Scripts;C:\Tools"
    )


def test_remove_path_value_strips_matching_entry_once() -> None:
    trimmed = _installer_module().remove_path_value(
        r"C:\Archon\bin;C:\Tools;C:\Archon\bin",
        Path(r"c:\archon\bin"),
        platform_name="win32",
    )

    assert trimmed == r"C:\Tools"


def test_render_windows_shims_target_repo_runtime() -> None:
    module = _installer_module()
    cmd = module.render_windows_cmd_shim("-m", "archon.archon_cli", "serve")
    ps1 = module.render_windows_ps1_shim("-m", "archon.archon_cli")

    assert '"%~dp0..\\venv\\Scripts\\python.exe" -m archon.archon_cli serve %*' in cmd
    assert '"$PSScriptRoot\\..\\venv\\Scripts\\python.exe" -m archon.archon_cli @args' in ps1


def test_render_posix_shim_targets_repo_runtime() -> None:
    module = _installer_module()
    shim = module.render_posix_shim("-m", "archon.archon_cli", "serve")

    assert "#!/usr/bin/env sh" in shim
    assert '"$SCRIPT_DIR/../venv/bin/python" -m archon.archon_cli serve "$@"' in shim


def test_resolve_command_path_returns_none_when_unavailable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from archon import runtime_installer

    monkeypatch.setattr(runtime_installer.shutil, "which", lambda *_args, **_kwargs: None)

    resolved = runtime_installer.resolve_command_path("archon")

    assert resolved is None


def test_resolve_command_path_wraps_shutil_which_result(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from archon import runtime_installer

    shim = tmp_path / "archon.cmd"
    shim.write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setattr(runtime_installer.shutil, "which", lambda *_args, **_kwargs: str(shim))

    resolved = runtime_installer.resolve_command_path("archon")

    assert resolved == shim.resolve()


def test_default_install_root_uses_user_local_programs_on_windows(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\visha\AppData\Local")

    path = _installer_module().default_install_root("win32")

    assert path == Path(r"C:\Users\visha\AppData\Local\Programs\Archon")


def test_default_install_root_falls_back_to_userprofile_on_windows(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("USERPROFILE", r"C:\Users\visha")

    path = _installer_module().default_install_root("win32")

    assert path == Path(r"C:\Users\visha\AppData\Local\Programs\Archon")


def test_default_install_root_uses_user_local_share_on_linux() -> None:
    path = _installer_module().default_install_root("linux")

    assert path == Path.home() / ".local" / "share" / "archon"


def test_default_install_root_uses_application_support_on_macos() -> None:
    path = _installer_module().default_install_root("darwin")

    assert path == Path.home() / "Library" / "Application Support" / "Archon"


def test_ensure_user_path_updates_bash_profile_on_linux(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from archon import runtime_installer

    bin_dir = tmp_path / "archon" / "bin"
    monkeypatch.setattr(runtime_installer.sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/bash")

    updated = runtime_installer._ensure_user_path(bin_dir)

    profile = (tmp_path / ".bashrc").read_text(encoding="utf-8")
    assert updated is True
    assert "ARCHON PATH" in profile
    assert str(bin_dir) in profile
    assert str(bin_dir) in str(runtime_installer.os.environ["PATH"])


def test_remove_user_path_cleans_shell_profiles_on_linux(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from archon import runtime_installer

    bin_dir = tmp_path / "archon" / "bin"
    profile = tmp_path / ".bashrc"
    profile.write_text(runtime_installer._render_posix_path_block(bin_dir), encoding="utf-8")
    monkeypatch.setattr(runtime_installer.sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/bash")

    updated = runtime_installer._remove_user_path(bin_dir)

    assert updated is True
    assert profile.read_text(encoding="utf-8") == ""


def test_uninstall_removes_runtime_tree_on_non_windows(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from archon import runtime_installer

    install_root = tmp_path / "Archon"
    (install_root / "bin").mkdir(parents=True)
    monkeypatch.setattr(runtime_installer.sys, "platform", "linux")
    monkeypatch.setattr(runtime_installer, "_remove_user_path", lambda *_args, **_kwargs: False)

    exit_code = runtime_installer.uninstall(
        install_root=install_root,
        skip_path=False,
    )

    assert exit_code == 0
    assert not install_root.exists()


def test_uninstall_schedules_cleanup_on_windows(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from archon import runtime_installer

    install_root = tmp_path / "Archon"
    install_root.mkdir()
    scheduled: list[Path] = []
    cleanup_script = tmp_path / "cleanup.cmd"
    monkeypatch.setattr(runtime_installer.sys, "platform", "win32")
    monkeypatch.setattr(runtime_installer, "_remove_user_path", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        runtime_installer,
        "_schedule_windows_uninstall",
        lambda path: scheduled.append(path) or cleanup_script,
    )

    exit_code = runtime_installer.uninstall(
        install_root=install_root,
        skip_path=False,
    )

    assert exit_code == 0
    assert scheduled == [install_root]
