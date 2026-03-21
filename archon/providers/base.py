"""Base provider interface for ARCHON."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from archon.providers.types import ProviderName, ProviderResponse, ProviderRole


class BaseProvider(ABC):
    """Abstract base class for all LLM providers."""

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url or self.default_base_url()
        self._client: httpx.AsyncClient | None = None

    @classmethod
    @abstractmethod
    def name(cls) -> ProviderName:
        """Return the provider name."""
        pass

    @classmethod
    @abstractmethod
    def default_base_url(cls) -> str:
        """Return the default base URL for this provider."""
        pass

    @classmethod
    @abstractmethod
    def default_model(cls, role: ProviderRole) -> str:
        """Return the default model for a given role."""
        pass

    @classmethod
    @abstractmethod
    def env_key(cls) -> str:
        """Return the environment variable name for the API key."""
        pass

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        """Execute a chat completion request."""
        pass

    @abstractmethod
    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        """Estimate the cost in USD for given token counts."""
        pass

    async def get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(60.0, connect=10.0),
                headers=self._auth_headers(),
            )
        return self._client

    async def aclose(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _auth_headers(self) -> dict[str, str]:
        """Return authentication headers for requests."""
        return {"Authorization": f"Bearer {self.api_key}"}

    def _build_messages_payload(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Build the request payload for chat completion."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        return payload

    def _parse_response(self, raw: Any) -> ProviderResponse:
        """Parse the raw API response into a ProviderResponse."""
        raise NotImplementedError
