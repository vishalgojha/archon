"""Tool registry for function-calling tools."""

from __future__ import annotations

from typing import Iterable

from archon.tooling.base import BaseTool


class ToolRegistry:
    def __init__(self, tools: Iterable[BaseTool] | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: BaseTool) -> None:
        name = str(tool.name).strip()
        if not name:
            raise ValueError("Tool name is required.")
        self._tools[name] = tool

    def list_tools(self) -> dict[str, BaseTool]:
        return dict(self._tools)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def openai_schema(self) -> list[dict[str, object]]:
        schemas: list[dict[str, object]] = []
        for tool in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
            )
        return schemas

    def anthropic_schema(self) -> list[dict[str, object]]:
        schemas: list[dict[str, object]] = []
        for tool in self._tools.values():
            schemas.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
            )
        return schemas
