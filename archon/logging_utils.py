"""Lightweight file logging helpers for ARCHON."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


def _default_log_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA", "").strip()
        if base:
            return Path(base) / "Archon" / "logs"
        return Path.home() / "AppData" / "Local" / "Archon" / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Archon" / "logs"
    return Path.home() / ".local" / "share" / "archon" / "logs"


def log_dir() -> Path:
    override = os.environ.get("ARCHON_LOG_DIR", "").strip()
    if override:
        return Path(override)
    return _default_log_dir()


def log_path(filename: str) -> Path:
    return log_dir() / filename


def append_log(filename: str, message: str) -> None:
    path = log_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    line = f"[{timestamp}] {message}"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
