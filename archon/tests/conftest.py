"""Pytest fixtures for ARCHON tests with proper cleanup."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Generator

import pytest

from archon.config import ArchonConfig


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_db_path(temp_dir: Path) -> Generator[Path, None, None]:
    """Create a temporary database path that is cleaned up after the test."""
    db_path = temp_dir / "test.db"
    yield db_path
    # Cleanup is handled by temp_dir fixture


@pytest.fixture
def mock_env_vars() -> Generator[None, None, None]:
    """Mock environment variables for testing, cleaned up after test."""
    original_env = os.environ.copy()
    try:
        yield
    finally:
        # Restore original environment
        os.environ.clear()
        os.environ.update(original_env)


@pytest.fixture
def sample_config() -> ArchonConfig:
    """Create a sample configuration for testing."""
    return ArchonConfig.model_validate(
        {
            "byok": {
                "primary": "anthropic",
                "coding": "openai",
                "budget_per_task_usd": 1.0,
            },
            "memory": {"enabled": True, "db_path": ":memory:"},
            "evolution": {"enabled": False},
            "skills": {"enabled": False},
            "ui_packs": {"enabled": False},
            "observability": {"enabled": False},
            "billing": {"enabled": False},
            "analytics": {"enabled": False},
            "studio": {"enabled": False},
            "marketplace": {"enabled": False},
            "mobile_sync": {"enabled": False},
            "partners": {"enabled": False},
            "compliance": {"enabled": False},
        }
    )


@pytest.fixture
def sample_messages() -> list[dict[str, str]]:
    """Sample conversation messages for testing."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, how are you?"},
    ]


@pytest.fixture
def sample_task_context() -> dict[str, Any]:
    """Sample task context for testing."""
    return {
        "goal": "Explain CAP theorem simply",
        "mode": "swarm",
        "language": "en",
    }


@pytest.fixture
def cleanup_callback() -> Generator[list[Callable[[], Any]], None, None]:
    """Track cleanup callbacks to be executed after test."""
    callbacks: list[Callable[[], Any]] = []
    yield callbacks
    for callback in callbacks:
        callback()
