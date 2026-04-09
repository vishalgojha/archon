"""Tests for system tools including GlobTool and GrepTool."""

from __future__ import annotations

from pathlib import Path

import pytest

from archon.tooling.safety import PathPolicy
from archon.tooling.system_tools import GlobTool, GrepTool, build_system_tool_registry


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project structure for testing."""
    # Create some Python files
    (tmp_path / "main.py").write_text("import os\nprint('hello')\n")
    (tmp_path / "utils.py").write_text("def helper():\n    return 42\n")
    (tmp_path / "config.yaml").write_text("key: value\n")

    # Create a subdirectory
    subdir = tmp_path / "src"
    subdir.mkdir()
    (subdir / "app.py").write_text("from utils import helper\nprint(helper())\n")
    (subdir / "types.ts").write_text("export interface User {\n  name: string;\n}\n")

    return tmp_path


@pytest.fixture
def policy(tmp_path: Path) -> PathPolicy:
    """Create a PathPolicy allowing access to tmp_path."""
    return PathPolicy(allow_roots=[str(tmp_path)])


class TestGlobTool:
    @pytest.mark.asyncio
    async def test_glob_simple(self, tmp_project: Path, policy: PathPolicy) -> None:
        tool = GlobTool(policy=policy)
        result = await tool.execute(pattern="*.py", path=str(tmp_project))
        assert result.ok
        assert "main.py" in result.output
        assert "utils.py" in result.output
        assert "app.py" not in result.output  # in subdirectory

    @pytest.mark.asyncio
    async def test_glob_recursive(self, tmp_project: Path, policy: PathPolicy) -> None:
        tool = GlobTool(policy=policy)
        result = await tool.execute(pattern="**/*.py", path=str(tmp_project))
        assert result.ok
        assert "main.py" in result.output
        # Check for app.py in any subdirectory (handles both / and \)
        assert "app.py" in result.output

    @pytest.mark.asyncio
    async def test_glob_all_files(self, tmp_project: Path, policy: PathPolicy) -> None:
        tool = GlobTool(policy=policy)
        result = await tool.execute(pattern="**/*", path=str(tmp_project))
        assert result.ok
        assert "main.py" in result.output
        assert "config.yaml" in result.output
        # Check for app.py in any subdirectory (handles both / and \)
        assert "app.py" in result.output

    @pytest.mark.asyncio
    async def test_glob_no_matches(self, tmp_project: Path, policy: PathPolicy) -> None:
        tool = GlobTool(policy=policy)
        result = await tool.execute(pattern="**/*.xyz", path=str(tmp_project))
        assert result.ok
        assert "no files" in result.output

    @pytest.mark.asyncio
    async def test_glob_missing_pattern(self, policy: PathPolicy) -> None:
        tool = GlobTool(policy=policy)
        result = await tool.execute(pattern="")
        assert not result.ok
        assert "pattern is required" in result.output


class TestGrepTool:
    @pytest.mark.asyncio
    async def test_grep_simple(self, tmp_project: Path, policy: PathPolicy) -> None:
        tool = GrepTool(policy=policy)
        result = await tool.execute(pattern="import", path=str(tmp_project))
        assert result.ok
        assert "main.py" in result.output
        assert "app.py" in result.output

    @pytest.mark.asyncio
    async def test_grep_with_include(self, tmp_project: Path, policy: PathPolicy) -> None:
        tool = GrepTool(policy=policy)
        result = await tool.execute(pattern="import", path=str(tmp_project), include="*.py")
        assert result.ok
        assert "main.py" in result.output
        assert "app.py" in result.output

    @pytest.mark.asyncio
    async def test_grep_case_insensitive(self, tmp_project: Path, policy: PathPolicy) -> None:
        tool = GrepTool(policy=policy)
        result = await tool.execute(pattern="HELLO", path=str(tmp_project))
        assert result.ok
        assert "main.py" in result.output

    @pytest.mark.asyncio
    async def test_grep_no_matches(self, tmp_project: Path, policy: PathPolicy) -> None:
        tool = GrepTool(policy=policy)
        result = await tool.execute(pattern="nonexistent_pattern_xyz", path=str(tmp_project))
        assert result.ok
        assert "no matches" in result.output

    @pytest.mark.asyncio
    async def test_grep_invalid_regex(self, policy: PathPolicy) -> None:
        tool = GrepTool(policy=policy)
        result = await tool.execute(pattern="[invalid", path=".")
        assert not result.ok
        assert "invalid regex" in result.output

    @pytest.mark.asyncio
    async def test_grep_line_numbers(self, tmp_project: Path, policy: PathPolicy) -> None:
        tool = GrepTool(policy=policy)
        result = await tool.execute(pattern="print", path=str(tmp_project))
        assert result.ok
        assert ":1:" in result.output or ":2:" in result.output


class TestBuildSystemToolRegistry:
    def test_includes_all_tools(self) -> None:
        reg = build_system_tool_registry()
        tools = reg.list_tools()
        assert "shell" in tools
        assert "read_file" in tools
        assert "write_file" in tools
        assert "list_dir" in tools
        assert "glob" in tools
        assert "grep" in tools
