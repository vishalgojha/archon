"""Safety boundaries for tool execution."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_WINDOWS_BLOCKLIST = [
    r"C:\\Windows",
    r"C:\\Program Files",
    r"C:\\Program Files (x86)",
    r"C:\\ProgramData",
    r"C:\\System Volume Information",
    r"C:\\$Recycle.Bin",
]

DEFAULT_POSIX_BLOCKLIST = [
    "/bin",
    "/sbin",
    "/usr",
    "/lib",
    "/etc",
    "/var",
    "/System",
    "/Library",
]


class PathPolicy:
    """Allow only user-profile + repo roots, and block system directories."""

    def __init__(
        self,
        allow_roots: list[str] | None = None,
        extra_blocked: list[str] | None = None,
    ) -> None:
        if allow_roots is None:
            allow_roots = [str(Path.home()), str(Path.cwd())]
        self._allow_roots = [self._normalize_root(path) for path in allow_roots]

        if os.name == "nt":
            blocked = list(DEFAULT_WINDOWS_BLOCKLIST)
        else:
            blocked = list(DEFAULT_POSIX_BLOCKLIST)
        if extra_blocked:
            blocked.extend(extra_blocked)
        self._blocked = [self._normalize_root(path) for path in blocked]

    def assert_allowed(self, path: str) -> Path:
        resolved = self._normalize_path(path)
        if self._allow_roots and not any(
            _is_relative_to(resolved, root) for root in self._allow_roots
        ):
            raise PermissionError(f"Access denied outside allowed roots: {resolved}")
        for blocked in self._blocked:
            if _is_relative_to(resolved, blocked):
                raise PermissionError(f"Access denied for system path: {resolved}")
        return resolved

    def command_allowed(self, command: str) -> bool:
        if not command:
            return False
        lowered = command.lower()
        for blocked in self._blocked:
            if str(blocked).lower() in lowered:
                return False
            alt = str(blocked).replace("\\", "/").lower()
            if alt in lowered:
                return False
        return True

    def _normalize_path(self, path: str) -> Path:
        expanded = os.path.expandvars(os.path.expanduser(path))
        return Path(expanded).resolve()

    def _normalize_root(self, path: str) -> Path:
        expanded = os.path.expandvars(os.path.expanduser(path))
        return Path(expanded).resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        return path == root or path.is_relative_to(root)
    except AttributeError:
        try:
            path.relative_to(root)
            return True
        except Exception:
            return False
