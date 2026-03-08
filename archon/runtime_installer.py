"""User-local ARCHON runtime install and uninstall helpers."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]


def default_install_root(platform_name: str | None = None) -> Path:
    """Return the default user-local install directory.

    Example:
        Input: ``platform_name="win32"``
        Output: ``Path("C:/Users/<user>/AppData/Local/Programs/Archon")``
    """

    platform_name = (platform_name or sys.platform).lower()
    if platform_name.startswith("win"):
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        if local_appdata:
            return Path(local_appdata) / "Programs" / "Archon"
        return Path.home() / "AppData" / "Local" / "Programs" / "Archon"
    if platform_name == "darwin":
        return Path.home() / "Library" / "Application Support" / "Archon"
    return Path.home() / ".local" / "share" / "archon"


def load_dependency_specs(pyproject_path: Path, *, include_dev: bool = False) -> list[str]:
    """Load dependency specs from ``pyproject.toml``.

    Example:
        Input: ``include_dev=False``
        Output: ``["click>=8.1.7", ...]``
    """

    with pyproject_path.open("rb") as handle:
        payload = tomllib.load(handle)
    project = payload.get("project", {})
    resolved: list[str] = []

    def append_unique(values: Sequence[str]) -> None:
        for value in values:
            normalized = str(value).strip()
            if normalized and normalized not in resolved:
                resolved.append(normalized)

    append_unique(project.get("dependencies", []))
    if include_dev:
        optional = project.get("optional-dependencies", {})
        append_unique(optional.get("dev", []))
    return resolved


def merge_path_value(
    existing: str,
    new_entry: Path,
    *,
    platform_name: str | None = None,
    prioritize: bool = False,
) -> str:
    """Add one PATH entry once, optionally moving it to the front.

    Example:
        Input: ``existing="C:\\Tools"``, ``new_entry=Path("C:\\Archon\\bin")``
        Output: ``"C:\\Tools;C:\\Archon\\bin"``
    """

    platform_name = (platform_name or sys.platform).lower()
    separator = ";" if platform_name.startswith("win") else os.pathsep
    current = [item for item in str(existing or "").split(separator) if item.strip()]
    candidate = str(new_entry)

    def normalize(value: str) -> str:
        normalized = os.path.normpath(os.path.expandvars(str(value).strip()))
        if platform_name.startswith("win"):
            normalized = os.path.normcase(normalized)
        return normalized

    candidate_norm = normalize(candidate)
    if not prioritize and any(normalize(item) == candidate_norm for item in current):
        return separator.join(current)
    filtered = [item for item in current if normalize(item) != candidate_norm]
    if prioritize:
        current = [candidate, *filtered]
    else:
        current = [*filtered, candidate]
    return separator.join(current)


def remove_path_value(
    existing: str,
    entry: Path,
    *,
    platform_name: str | None = None,
) -> str:
    """Remove one PATH entry if present.

    Example:
        Input: ``existing="C:\\Archon\\bin;C:\\Tools"``
        Output: ``"C:\\Tools"``
    """

    platform_name = (platform_name or sys.platform).lower()
    separator = ";" if platform_name.startswith("win") else os.pathsep
    current = [item for item in str(existing or "").split(separator) if item.strip()]
    candidate = str(entry)

    def normalize(value: str) -> str:
        normalized = os.path.normpath(os.path.expandvars(str(value).strip()))
        if platform_name.startswith("win"):
            normalized = os.path.normcase(normalized)
        return normalized

    candidate_norm = normalize(candidate)
    filtered = [item for item in current if normalize(item) != candidate_norm]
    return separator.join(filtered)


def render_windows_cmd_shim(*python_args: str) -> str:
    """Render the ``archon.cmd`` shim contents.

    Example:
        Input: ``("-m", "archon.archon_cli")``
        Output: a batch script that runs the dedicated ARCHON Python runtime.
    """

    suffix = " ".join(python_args)
    return "\n".join(
        [
            "@echo off",
            "setlocal",
            f'"%~dp0..\\venv\\Scripts\\python.exe" {suffix} %*',
            "",
        ]
    )


def render_windows_ps1_shim(*python_args: str) -> str:
    """Render the ``archon.ps1`` shim contents.

    Example:
        Input: ``("-m", "archon.archon_cli", "serve")``
        Output: a PowerShell launcher for the dedicated ARCHON runtime.
    """

    suffix = " ".join(python_args)
    return "\n".join(
        [
            f'& "$PSScriptRoot\\..\\venv\\Scripts\\python.exe" {suffix} @args',
            "",
        ]
    )


def resolve_command_path(command_name: str, *, path_value: str | None = None) -> Path | None:
    """Resolve an executable or shim in ``PATH``.

    Example:
        Input: ``command_name="archon"``
        Output: ``Path(".../archon.cmd")`` or ``None``
    """

    resolved = shutil.which(command_name, path=path_value)
    if not resolved:
        return None
    try:
        return Path(resolved).resolve()
    except OSError:
        return Path(resolved)


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _run(command: Sequence[str], *, cwd: Path | None = None, dry_run: bool = False) -> None:
    printable = " ".join(str(part) for part in command)
    print(f"[archon-installer] {printable}")
    if dry_run:
        return
    subprocess.run(command, cwd=str(cwd) if cwd is not None else None, check=True)


def _query_purelib(venv_python: Path, *, dry_run: bool = False) -> Path:
    if dry_run:
        return Path("<purelib>")
    value = subprocess.check_output(
        [str(venv_python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        text=True,
    ).strip()
    return Path(value)


def _ensure_venv(venv_dir: Path, *, dry_run: bool = False) -> Path:
    venv_python = _venv_python(venv_dir)
    if venv_python.exists():
        return venv_python
    print(f"[archon-installer] Creating virtual environment at {venv_dir}")
    if not dry_run:
        venv.EnvBuilder(with_pip=True).create(str(venv_dir))
    return venv_python


def _write_text(path: Path, content: str, *, dry_run: bool = False) -> None:
    print(f"[archon-installer] Writing {path}")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_source_pth(
    purelib_dir: Path,
    *,
    repo_root: Path,
    dry_run: bool = False,
) -> None:
    _write_text(purelib_dir / "archon_repo.pth", f"{repo_root.resolve()}\n", dry_run=dry_run)


def _write_manifest(
    install_root: Path,
    *,
    repo_root: Path,
    include_dev: bool,
    dry_run: bool = False,
) -> None:
    payload = {
        "repo_root": str(repo_root.resolve()),
        "install_root": str(install_root.resolve()),
        "include_dev": include_dev,
        "python": sys.executable,
    }
    _write_text(
        install_root / "install-manifest.json",
        json.dumps(payload, indent=2) + "\n",
        dry_run=dry_run,
    )


def _write_windows_shims(bin_dir: Path, *, dry_run: bool = False) -> None:
    _write_text(
        bin_dir / "archon.cmd",
        render_windows_cmd_shim("-m", "archon.archon_cli"),
        dry_run=dry_run,
    )
    _write_text(
        bin_dir / "archon.ps1",
        render_windows_ps1_shim("-m", "archon.archon_cli"),
        dry_run=dry_run,
    )
    _write_text(
        bin_dir / "archon-server.cmd",
        render_windows_cmd_shim("-m", "archon.archon_cli", "serve"),
        dry_run=dry_run,
    )
    _write_text(
        bin_dir / "archon-server.ps1",
        render_windows_ps1_shim("-m", "archon.archon_cli", "serve"),
        dry_run=dry_run,
    )


def _print_resolution_guidance(bin_dir: Path) -> None:
    expected_dir = bin_dir.resolve()
    resolved = resolve_command_path("archon", path_value=os.environ.get("PATH"))
    if resolved is not None and resolved.parent == expected_dir:
        print(f"  Launcher:     {resolved}")
        return

    print("  Launcher:     unresolved conflict")
    if resolved is not None:
        print(f"  Resolved to:  {resolved}")
    print(f"  Expected:     {expected_dir / 'archon.cmd'}")
    print("  Fix now:      open a new shell or run the .cmd shim directly")


def _broadcast_environment_change() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        result = ctypes.c_void_p()
        ctypes.windll.user32.SendMessageTimeoutW(  # type: ignore[attr-defined]
            0xFFFF,
            0x001A,
            0,
            "Environment",
            0x0002,
            5000,
            ctypes.byref(result),
        )
    except Exception:
        return


def _ensure_user_path(bin_dir: Path, *, dry_run: bool = False) -> bool:
    if not sys.platform.startswith("win"):
        return False
    import winreg

    updated = False
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
        try:
            current, value_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current = ""
            value_type = winreg.REG_EXPAND_SZ
        merged = merge_path_value(
            str(current or ""),
            bin_dir,
            platform_name="win32",
            prioritize=True,
        )
        if merged != str(current or ""):
            print(f"[archon-installer] Adding {bin_dir} to the user PATH")
            updated = True
            if not dry_run:
                winreg.SetValueEx(
                    key,
                    "Path",
                    0,
                    value_type
                    if value_type in {winreg.REG_EXPAND_SZ, winreg.REG_SZ}
                    else winreg.REG_EXPAND_SZ,
                    merged,
                )
    os.environ["PATH"] = merge_path_value(
        os.environ.get("PATH", ""),
        bin_dir,
        platform_name="win32",
        prioritize=True,
    )
    if updated and not dry_run:
        _broadcast_environment_change()
    return updated


def _remove_user_path(bin_dir: Path, *, dry_run: bool = False) -> bool:
    if not sys.platform.startswith("win"):
        return False
    import winreg

    updated = False
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
        try:
            current, value_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current = ""
            value_type = winreg.REG_EXPAND_SZ
        trimmed = remove_path_value(
            str(current or ""),
            bin_dir,
            platform_name="win32",
        )
        if trimmed != str(current or ""):
            print(f"[archon-installer] Removing {bin_dir} from the user PATH")
            updated = True
            if not dry_run:
                winreg.SetValueEx(
                    key,
                    "Path",
                    0,
                    value_type
                    if value_type in {winreg.REG_EXPAND_SZ, winreg.REG_SZ}
                    else winreg.REG_EXPAND_SZ,
                    trimmed,
                )
    os.environ["PATH"] = remove_path_value(
        os.environ.get("PATH", ""),
        bin_dir,
        platform_name="win32",
    )
    if updated and not dry_run:
        _broadcast_environment_change()
    return updated


def _validate_runtime() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit(
            "ARCHON requires Python 3.11+. Re-run install.cmd after installing Python 3.11 or newer."
        )


def _schedule_windows_uninstall(install_root: Path, *, dry_run: bool = False) -> Path:
    script_path = Path(tempfile.gettempdir()) / f"archon-uninstall-{os.getpid()}.cmd"
    script_text = "\n".join(
        [
            "@echo off",
            "setlocal",
            f'set "TARGET={install_root.resolve()}"',
            ":retry",
            'rmdir /s /q "%TARGET%" >nul 2>nul',
            'if exist "%TARGET%" (',
            "  ping -n 2 127.0.0.1 >nul",
            "  goto retry",
            ")",
            'del /f /q "%~f0" >nul 2>nul',
            "",
        ]
    )
    _write_text(script_path, script_text, dry_run=dry_run)
    if dry_run:
        return script_path

    creationflags = 0
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(  # noqa: S603
        ["cmd.exe", "/c", str(script_path)],
        creationflags=creationflags,
        close_fds=True,
    )
    return script_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install ARCHON globally for the current user.")
    parser.add_argument(
        "--home",
        default=str(default_install_root()),
        help="Install root directory. Defaults to a user-local Archon home.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(_REPO_ROOT),
        help="Repository root to expose to the installed runtime.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Install development dependencies in the dedicated ARCHON runtime.",
    )
    parser.add_argument(
        "--skip-path",
        action="store_true",
        help="Do not add the generated bin directory to the user PATH.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without creating files or installing dependencies.",
    )
    return parser


def install(
    *, repo_root: Path, install_root: Path, include_dev: bool, skip_path: bool, dry_run: bool
) -> int:
    """Install ARCHON into a dedicated user-local runtime.

    Example:
        Input: ``repo_root=Path.cwd(), install_root=default_install_root(), dry_run=True``
        Output: ``0``
    """

    _validate_runtime()
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        raise SystemExit(f"Could not find {pyproject_path}")
    dependencies = load_dependency_specs(pyproject_path, include_dev=include_dev)
    if not dependencies:
        raise SystemExit(f"No dependencies found in {pyproject_path}")

    venv_dir = install_root / "venv"
    bin_dir = install_root / "bin"
    venv_python = _ensure_venv(venv_dir, dry_run=dry_run)
    _run(
        [str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        cwd=repo_root,
        dry_run=dry_run,
    )
    _run(
        [str(venv_python), "-m", "pip", "install", "--upgrade", *dependencies],
        cwd=repo_root,
        dry_run=dry_run,
    )
    purelib_dir = _query_purelib(venv_python, dry_run=dry_run)
    _write_source_pth(purelib_dir, repo_root=repo_root, dry_run=dry_run)
    _write_windows_shims(bin_dir, dry_run=dry_run)
    _write_manifest(install_root, repo_root=repo_root, include_dev=include_dev, dry_run=dry_run)

    path_updated = False
    if not skip_path:
        path_updated = _ensure_user_path(bin_dir, dry_run=dry_run)

    print("")
    print("ARCHON global install complete.")
    print(f"  Repo root:    {repo_root.resolve()}")
    print(f"  Runtime:      {venv_dir}")
    print(f"  Commands:     {bin_dir}")
    print(f"  Dependencies: {'base + dev' if include_dev else 'base'}")
    _print_resolution_guidance(bin_dir)
    if dry_run:
        print("  Mode:         dry-run")
    elif path_updated:
        print("  PATH:         updated for the current user")
    elif skip_path:
        print("  PATH:         unchanged (--skip-path)")
    else:
        print("  PATH:         already contains the ARCHON bin directory")
    print("")
    print("Use this immediately in the current shell if PATH is still stale:")
    print(f"  {bin_dir / 'archon.cmd'} version")
    print("")
    print("Open a new shell, then run:")
    print("  archon version")
    print("  archon onboard")
    print("  archon serve")
    return 0


def uninstall(*, install_root: Path, skip_path: bool, dry_run: bool) -> int:
    """Remove the dedicated ARCHON runtime and its PATH entry.

    Example:
        Input: ``install_root=default_install_root(), dry_run=True``
        Output: ``0``
    """

    bin_dir = install_root / "bin"
    path_updated = False
    if not skip_path:
        path_updated = _remove_user_path(bin_dir, dry_run=dry_run)

    print("")
    if dry_run:
        print("ARCHON uninstall preview.")
        print(f"  Runtime:      {install_root}")
        print(f"  Commands:     {bin_dir}")
        print(f"  PATH change:  {'yes' if path_updated else 'no'}")
        print("")
        return 0

    if not install_root.exists():
        print("ARCHON runtime not found.")
        print(f"  Expected:     {install_root}")
        if path_updated:
            print("  PATH:         cleaned up")
        print("")
        return 0

    if sys.platform.startswith("win"):
        script_path = _schedule_windows_uninstall(install_root, dry_run=False)
        print("ARCHON uninstall scheduled.")
        print(f"  Runtime:      {install_root}")
        print(f"  Cleanup:      {script_path}")
        print(
            "  PATH:         " + ("updated for the current user" if path_updated else "unchanged")
        )
        print("")
        print("Open a new shell after this command exits.")
        return 0

    shutil.rmtree(install_root)
    print("ARCHON uninstall complete.")
    print(f"  Removed:      {install_root}")
    print("  PATH:         " + ("updated for the current user" if path_updated else "unchanged"))
    print("")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone installer entrypoint.

    Example:
        Input: ``argv=["--dry-run"]``
        Output: ``0``
    """

    parser = _build_parser()
    args = parser.parse_args(argv)
    return install(
        repo_root=Path(args.repo_root),
        install_root=Path(args.home),
        include_dev=bool(args.dev),
        skip_path=bool(args.skip_path),
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    raise SystemExit(main())
