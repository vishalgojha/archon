"""System tools for file system and shell access."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from archon.tooling.base import BaseTool, ToolResult
from archon.tooling.registry import ToolRegistry
from archon.tooling.safety import PathPolicy


def _truncate(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


@dataclass(slots=True)
class ShellTool(BaseTool):
    policy: PathPolicy
    name: str = "shell"
    description: str = "Run a shell command on the host system."
    input_schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.input_schema = {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run."},
                "timeout_s": {"type": "number", "description": "Timeout in seconds."},
                "workdir": {"type": "string", "description": "Working directory."},
            },
            "required": ["command"],
            "additionalProperties": False,
        }

    async def execute(self, **kwargs) -> ToolResult:
        command = str(kwargs.get("command", "")).strip()
        if not command:
            return ToolResult(ok=False, output="command is required")
        if not self.policy.command_allowed(command):
            return ToolResult(ok=False, output="command references blocked system paths")

        timeout_s = float(kwargs.get("timeout_s", 60.0) or 60.0)
        workdir = kwargs.get("workdir")
        cwd = None
        try:
            if workdir:
                cwd = str(self.policy.assert_allowed(str(workdir)))
            else:
                cwd = str(self.policy.assert_allowed(str(Path.cwd())))
        except Exception as exc:
            return ToolResult(ok=False, output=str(exc))

        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=timeout_s,
            )
        except Exception as exc:
            return ToolResult(ok=False, output=str(exc))

        output = (completed.stdout or "") + (completed.stderr or "")
        output = _truncate(output.strip())
        return ToolResult(
            ok=completed.returncode == 0,
            output=output,
            metadata={"returncode": completed.returncode},
        )


@dataclass(slots=True)
class ReadFileTool(BaseTool):
    policy: PathPolicy
    name: str = "read_file"
    description: str = "Read a file from disk."
    input_schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.input_schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read."},
                "max_bytes": {"type": "integer", "description": "Max bytes to read."},
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    async def execute(self, **kwargs) -> ToolResult:
        raw_path = str(kwargs.get("path", "")).strip()
        if not raw_path:
            return ToolResult(ok=False, output="path is required")
        try:
            path = self.policy.assert_allowed(raw_path)
        except Exception as exc:
            return ToolResult(ok=False, output=str(exc))
        max_bytes = int(kwargs.get("max_bytes", 20000) or 20000)
        if not path.exists():
            return ToolResult(ok=False, output=f"file not found: {path}")
        try:
            data = path.read_bytes()
        except Exception as exc:
            return ToolResult(ok=False, output=str(exc))
        if max_bytes > 0:
            data = data[:max_bytes]
        text = data.decode("utf-8", errors="replace")
        return ToolResult(ok=True, output=text)


@dataclass(slots=True)
class WriteFileTool(BaseTool):
    policy: PathPolicy
    name: str = "write_file"
    description: str = "Write a file to disk."
    input_schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.input_schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write."},
                "content": {"type": "string", "description": "Content to write."},
                "append": {"type": "boolean", "description": "Append instead of overwrite."},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }

    async def execute(self, **kwargs) -> ToolResult:
        raw_path = str(kwargs.get("path", "")).strip()
        content = str(kwargs.get("content", ""))
        append = bool(kwargs.get("append", False))
        if not raw_path:
            return ToolResult(ok=False, output="path is required")
        try:
            path = self.policy.assert_allowed(raw_path)
        except Exception as exc:
            return ToolResult(ok=False, output=str(exc))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            if mode == "w":
                path.write_text(content, encoding="utf-8", errors="replace")
            else:
                with path.open(mode, encoding="utf-8", errors="replace") as handle:
                    handle.write(content)
        except Exception as exc:
            return ToolResult(ok=False, output=str(exc))
        return ToolResult(ok=True, output=f"wrote {len(content)} bytes to {path}")


@dataclass(slots=True)
class ListDirTool(BaseTool):
    policy: PathPolicy
    name: str = "list_dir"
    description: str = "List directory contents."
    input_schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.input_schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to list."},
                "limit": {"type": "integer", "description": "Max entries to return."},
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    async def execute(self, **kwargs) -> ToolResult:
        raw_path = str(kwargs.get("path", "")).strip()
        if not raw_path:
            return ToolResult(ok=False, output="path is required")
        try:
            path = self.policy.assert_allowed(raw_path)
        except Exception as exc:
            return ToolResult(ok=False, output=str(exc))
        if not path.exists():
            return ToolResult(ok=False, output=f"path not found: {path}")
        if not path.is_dir():
            return ToolResult(ok=False, output=f"path is not a directory: {path}")
        limit = int(kwargs.get("limit", 200) or 200)
        entries = []
        for item in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            info = {
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
            }
            if item.is_file():
                try:
                    info["size"] = item.stat().st_size
                except Exception:
                    info["size"] = None
            entries.append(info)
            if limit and len(entries) >= limit:
                break
        return ToolResult(ok=True, output=json.dumps(entries, ensure_ascii=False))


@dataclass(slots=True)
class GlobTool(BaseTool):
    """Find files matching a glob pattern."""

    policy: PathPolicy
    name: str = "glob"
    description: str = "Find files matching a glob pattern (e.g. **/*.py, src/**/*.ts)."
    input_schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.input_schema = {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match."},
                "path": {
                    "type": "string",
                    "description": "Directory to search in (defaults to current directory).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return.",
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }

    async def execute(self, **kwargs) -> ToolResult:
        pattern = str(kwargs.get("pattern", "")).strip()
        if not pattern:
            return ToolResult(ok=False, output="pattern is required")

        search_path_raw = str(kwargs.get("path", "")).strip()
        search_path = Path(search_path_raw) if search_path_raw else Path.cwd()

        try:
            resolved = self.policy.assert_allowed(str(search_path))
        except Exception as exc:
            return ToolResult(ok=False, output=str(exc))

        if not resolved.exists():
            return ToolResult(ok=False, output=f"path not found: {resolved}")
        if not resolved.is_dir():
            return ToolResult(ok=False, output=f"path is not a directory: {resolved}")

        max_results = int(kwargs.get("max_results", 500) or 500)
        matches: list[str] = []

        # Handle ** recursive glob
        if "**" in pattern:
            for path in resolved.rglob("*"):
                rel = path.relative_to(resolved)
                if fnmatch.fnmatch(str(rel), pattern) or fnmatch.fnmatch(
                    path.name, pattern.split("/")[-1]
                ):
                    matches.append(str(rel))
                    if len(matches) >= max_results:
                        break
        else:
            # Simple glob in current directory only
            for path in resolved.glob(pattern):
                rel = path.relative_to(resolved)
                matches.append(str(rel))
                if len(matches) >= max_results:
                    break

        matches.sort()
        if not matches:
            return ToolResult(ok=True, output=f"no files matching pattern: {pattern}")

        return ToolResult(ok=True, output="\n".join(matches))


@dataclass(slots=True)
class GrepTool(BaseTool):
    """Search file contents using a regex pattern."""

    policy: PathPolicy
    name: str = "grep"
    description: str = "Search file contents using a regex pattern. Returns matching lines with file and line number."
    input_schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.input_schema = {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for."},
                "path": {
                    "type": "string",
                    "description": "Directory to search in (defaults to current directory).",
                },
                "include": {
                    "type": "string",
                    "description": "File pattern to include (e.g. *.py, *.{ts,tsx}).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matching lines to return.",
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }

    async def execute(self, **kwargs) -> ToolResult:
        pattern = str(kwargs.get("pattern", "")).strip()
        if not pattern:
            return ToolResult(ok=False, output="pattern is required")

        try:
            regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        except re.error as exc:
            return ToolResult(ok=False, output=f"invalid regex: {exc}")

        search_path_raw = str(kwargs.get("path", "")).strip()
        search_path = Path(search_path_raw) if search_path_raw else Path.cwd()

        try:
            resolved = self.policy.assert_allowed(str(search_path))
        except Exception as exc:
            return ToolResult(ok=False, output=str(exc))

        if not resolved.exists():
            return ToolResult(ok=False, output=f"path not found: {resolved}")

        include_pattern = str(kwargs.get("include", "")).strip() or None
        max_results = int(kwargs.get("max_results", 200) or 200)

        results: list[str] = []
        files_searched = 0

        for path in resolved.rglob("*"):
            if not path.is_file():
                continue

            # Skip binary files and common non-text files
            skip_extensions = {".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".o", ".a"}
            if path.suffix in skip_extensions:
                continue

            # Apply include filter
            if include_pattern and not fnmatch.fnmatch(path.name, include_pattern):
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except (PermissionError, OSError):
                continue

            files_searched += 1
            rel_path = path.relative_to(resolved)

            for line_num, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    results.append(f"{rel_path}:{line_num}: {line.strip()}")
                    if len(results) >= max_results:
                        results.append(f"\n... truncated (searched {files_searched} files)")
                        return ToolResult(ok=True, output="\n".join(results))

        if not results:
            return ToolResult(
                ok=True,
                output=f"no matches for pattern: {pattern}\n(searched {files_searched} files)",
            )

        summary = f"\n---\n(searched {files_searched} files, {len(results)} matches)"
        return ToolResult(ok=True, output="\n".join(results) + summary)


def build_system_tool_registry(policy: PathPolicy | None = None) -> ToolRegistry:
    if policy is None:
        raw_roots = os.getenv("ARCHON_ALLOWED_ROOTS", "")
        allow_roots = [item.strip() for item in raw_roots.split(";") if item.strip()] or None
        policy = PathPolicy(allow_roots=allow_roots)
    tools = [
        ShellTool(policy=policy),
        ReadFileTool(policy=policy),
        WriteFileTool(policy=policy),
        ListDirTool(policy=policy),
        GlobTool(policy=policy),
        GrepTool(policy=policy),
    ]
    return ToolRegistry(tools)
