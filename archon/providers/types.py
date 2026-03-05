"""Typed provider contracts used by all ARCHON agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProviderSelection:
    """Resolved provider endpoint details for one request."""

    provider: str
    role: str
    model: str
    base_url: str
    api_key: str
    source: str = "built_in"
    endpoint_name: str | None = None


@dataclass(slots=True)
class ProviderUsage:
    """Token and cost usage returned by provider calls."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


@dataclass(slots=True)
class ProviderResponse:
    """Normalized provider response object shared by all agents."""

    text: str
    provider: str
    model: str
    usage: ProviderUsage
    raw: dict[str, Any] = field(default_factory=dict)
