"""Default tool registry builders for interactive chat sessions."""

from __future__ import annotations

from typing import Any

from archon.tooling.baileys_tools import BaileysSendMessageTool, BaileysStatusTool
from archon.tooling.registry import ToolRegistry
from archon.tooling.safety import PathPolicy
from archon.tooling.system_tools import build_system_tool_registry


def build_default_tool_registry(
    *,
    context: dict[str, Any] | None = None,
    policy: PathPolicy | None = None,
) -> ToolRegistry:
    registry = build_system_tool_registry(policy=policy)
    tool_context = dict(context or {})
    registry.register(BaileysStatusTool(context=tool_context))
    registry.register(BaileysSendMessageTool(context=tool_context))
    return registry
