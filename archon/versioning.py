"""Shared runtime version helpers for CLI and HTTP surfaces."""

from __future__ import annotations

import importlib.metadata
import subprocess
from pathlib import Path

ARCHON_VERSION_FALLBACK = "0.1.0"


def resolve_version() -> str:
    """Return the installed ARCHON package version.

    Example:
        Input: none
        Output: ``"0.1.0"``
    """

    try:
        return importlib.metadata.version("archon")
    except Exception:
        return ARCHON_VERSION_FALLBACK


def resolve_git_sha() -> str:
    """Return the current repository git SHA, or ``"unknown"``.

    Example:
        Input: none
        Output: ``"616378a"``
    """

    try:
        repo_root = Path(__file__).resolve().parents[1]
        value = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return value.strip() or "unknown"
    except Exception:
        return "unknown"
