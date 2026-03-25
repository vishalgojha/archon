"""Base definitions for tool-calling in ARCHON."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolResult:
    """Result returned by a tool execution."""

    ok: bool
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """Base class for all function-calling tools."""

    name: str
    description: str
    input_schema: dict[str, Any]

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        raise NotImplementedError
