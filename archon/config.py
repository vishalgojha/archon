"""Configuration models and loading helpers for ARCHON."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

SUPPORTED_PROVIDERS = {
    "anthropic",
    "openai",
    "gemini",
    "mistral",
    "groq",
    "together",
    "fireworks",
    "openrouter",
    "ollama",
}


class CustomEndpointConfig(BaseModel):
    """OpenAI-compatible custom endpoint definition."""

    model_config = ConfigDict(extra="forbid")

    name: str
    base_url: str
    api_key: str = "none"
    models: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)


class ByokConfig(BaseModel):
    """Bring-your-own-key provider and budget configuration."""

    model_config = ConfigDict(extra="forbid")

    primary: str = "anthropic"
    coding: str = "openai"
    vision: str = "openai"
    fast: str = "groq"
    embedding: str = "ollama"
    fallback: str = "openrouter"

    budget_per_task_usd: float = 0.50
    budget_per_month_usd: float = 50.00
    prefer_cheapest: bool = False
    free_tier_first: bool = False

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_vision_model: str = "llava:34b"

    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_fallback_chain: list[str] = Field(
        default_factory=lambda: [
            "anthropic/claude-sonnet-4-5",
            "openai/gpt-4o",
            "meta-llama/llama-4-maverick:free",
        ]
    )

    custom_endpoints: list[CustomEndpointConfig] = Field(default_factory=list)


class ArchonConfig(BaseModel):
    """Top-level ARCHON runtime configuration."""

    model_config = ConfigDict(extra="allow")

    byok: ByokConfig = Field(default_factory=ByokConfig)


def load_archon_config(path: str | Path = "config.archon.yaml") -> ArchonConfig:
    """Load and validate ARCHON config from YAML.

    Example:
        >>> cfg = load_archon_config("config.archon.yaml")
        >>> cfg.byok.primary
        'anthropic'
    """

    config_path = Path(path)
    if not config_path.exists():
        return ArchonConfig()

    with config_path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}
    return ArchonConfig.model_validate(raw)
