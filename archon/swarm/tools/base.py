"""Base tool definition for SMB skills."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ToolResult:
    answer: str
    confidence: float
    sources: list[str]
    follow_up_needed: bool


class BaseSMBTool:
    name: str
    description: str

    async def execute(self, query: str, context: dict[str, Any]) -> ToolResult:
        raise NotImplementedError
