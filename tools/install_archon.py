"""Global installer for a checked-out ARCHON repository."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tomllib
import venv
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]


def default_install_root(platform_name: str | None = None) -> Path:
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


def render_windows_cmd_shim(*python_args: str) -> str:
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
    suffix = " ".join(python_args)
    return "\n".join(
        [
            f'& "$PSScriptRoot\\..\\venv\\Scripts\\python.exe" {suffix} @args',
            "",
        ]
    )


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


def _validate_runtime() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit(
            "ARCHON requires Python 3.11+. Re-run install.cmd after installing Python 3.11 or newer."
        )


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


def main(argv: Sequence[str] | None = None) -> int:
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
