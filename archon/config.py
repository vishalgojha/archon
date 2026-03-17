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
    ollama_primary_model: str = "llama3.3:70b"
    ollama_coding_model: str = "qwen2.5-coder:32b"
    ollama_fast_model: str = "llama3.2:3b"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_vision_model: str = "llava:34b"
    vision_model: str | None = None

    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_fallback_chain: list[str] = Field(
        default_factory=lambda: [
            "anthropic/claude-sonnet-4-5",
            "openai/gpt-4o",
            "meta-llama/llama-4-maverick:free",
        ]
    )

    custom_endpoints: list[CustomEndpointConfig] = Field(default_factory=list)


class AuthConfig(BaseModel):
    """JWT auth configuration shared across CLI and server."""

    model_config = ConfigDict(extra="forbid")

    jwt_secret: str | None = None


class SkillsConfig(BaseModel):
    """Skill routing and auto-proposal configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    auto_propose: bool = False
    staging_threshold: float = 0.75


class ArchonConfig(BaseModel):
    """Top-level ARCHON runtime configuration."""

    model_config = ConfigDict(extra="allow")

    byok: ByokConfig = Field(default_factory=ByokConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)


def resolve_config_path(path: str | Path = "config.archon.yaml") -> Path:
    """Resolve a config path, falling back to the repo root for relative defaults."""

    config_path = Path(path)
    if config_path.is_absolute() or config_path.exists():
        return config_path
    repo_candidate = Path(__file__).resolve().parents[1] / config_path
    if repo_candidate.exists():
        return repo_candidate
    return config_path


def load_archon_config(path: str | Path = "config.archon.yaml") -> ArchonConfig:
    """Load and validate ARCHON config from YAML.

    Example:
        >>> cfg = load_archon_config("config.archon.yaml")
        >>> cfg.byok.primary
        'anthropic'
    """

    config_path = resolve_config_path(path)
    if not config_path.exists():
        return ArchonConfig()

    with config_path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}
    return ArchonConfig.model_validate(raw)
