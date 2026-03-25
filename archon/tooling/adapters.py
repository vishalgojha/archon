"""Adapters for reusing swarm tools in the tool-calling loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from archon.tooling.base import BaseTool, ToolResult
from archon.swarm.tools.base import BaseSMBTool, ToolResult as SMBToolResult


@dataclass(slots=True)
class SMBToolAdapter(BaseTool):
    tool: BaseSMBTool
    context: dict[str, Any]
    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.name = self.tool.name
        self.description = self.tool.description
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "User query."},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    async def execute(self, **kwargs) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return ToolResult(ok=False, output="query is required")
        result: SMBToolResult = await self.tool.execute(query, self.context)
        return ToolResult(
            ok=not result.follow_up_needed,
            output=result.answer,
            metadata={
                "confidence": result.confidence,
                "sources": result.sources,
                "follow_up_needed": result.follow_up_needed,
            },
        )
