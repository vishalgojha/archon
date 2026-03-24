"""Type definitions for provider responses and usage tracking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ProviderRole = Literal["primary", "coding", "vision", "fast"]
ProviderName = Literal[
    "anthropic",
    "openai",
    "gemini",
    "mistral",
    "groq",
    "together",
    "fireworks",
    "openrouter",
    "ollama",
]


@dataclass
class ProviderSelection:
    """Result of provider selection logic."""

    provider: ProviderName
    model: str
    role: ProviderRole
    base_url: str | None = None
    api_key: str | None = None
    is_fallback: bool = False
    reason: str = ""
    source: str | None = None
    endpoint_name: str | None = None


@dataclass
class ProviderResponse:
    """Normalized response from any provider."""

    text: str
    provider: ProviderName
    model: str
    usage: dict[str, int]
    finish_reason: str | None = None
    raw: Any | None = None


@dataclass
class ProviderUsage:
    """Token and cost usage tracking."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float = 0.0
    model: str = ""
    provider: ProviderName | None = None

    def update_cost(self, cost_usd: float) -> None:
        """Update the cost in USD."""
        self.cost_usd = cost_usd
