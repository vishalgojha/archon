"""Unified BYOK provider router for all ARCHON agents."""

from __future__ import annotations

import math
import os
from typing import Any

import httpx

from archon.config import SUPPORTED_PROVIDERS, ArchonConfig
from archon.core.cost_governor import CostGovernor
from archon.providers.types import ProviderResponse, ProviderSelection, ProviderUsage


class ProviderUnavailableError(RuntimeError):
    """Raised when no configured provider can satisfy a request role."""


class ProviderCallError(RuntimeError):
    """Raised when provider API call fails."""


PROVIDER_ENV_KEY = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}


DEFAULT_BASE_URL = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com",
    "mistral": "https://api.mistral.ai/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


DEFAULT_MODEL_BY_ROLE = {
    "anthropic": {
        "primary": "claude-sonnet-4-5",
        "coding": "claude-sonnet-4-5",
        "vision": "claude-sonnet-4-5",
        "fast": "claude-3-5-haiku-latest",
    },
    "openai": {
        "primary": "o3",
        "coding": "gpt-4o",
        "vision": "gpt-4o",
        "fast": "gpt-4o-mini",
    },
    "gemini": {
        "primary": "gemini-2.0-pro",
        "coding": "gemini-2.0-flash",
        "vision": "gemini-2.0-flash",
        "fast": "gemini-2.0-flash",
    },
    "mistral": {
        "primary": "mistral-large-latest",
        "coding": "codestral-latest",
        "fast": "ministral-8b-latest",
    },
    "groq": {
        "fast": "llama-3.3-70b-versatile",
        "coding": "mixtral-8x7b-32768",
        "primary": "llama-3.3-70b-versatile",
    },
    "together": {
        "fast": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "coding": "deepseek-ai/DeepSeek-Coder-V2-Instruct",
        "primary": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },
    "fireworks": {
        "fast": "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "primary": "accounts/fireworks/models/llama-v3p3-70b-instruct",
    },
    "openrouter": {
        "primary": "anthropic/claude-sonnet-4-5",
        "coding": "openai/gpt-4o",
        "vision": "openai/gpt-4o",
        "fast": "meta-llama/llama-4-maverick:free",
    },
    "ollama": {
        "primary": "llama3.3:70b",
        "coding": "qwen2.5-coder:32b",
        "vision": "llava:34b",
        "fast": "llama3.2:3b",
        "embedding": "nomic-embed-text",
    },
}


TOKEN_PRICE_PER_1K = {
    "anthropic": {"input": 0.0030, "output": 0.0150},
    "openai": {"input": 0.0050, "output": 0.0150},
    "gemini": {"input": 0.0015, "output": 0.0030},
    "mistral": {"input": 0.0020, "output": 0.0060},
    "groq": {"input": 0.0006, "output": 0.0008},
    "together": {"input": 0.0008, "output": 0.0012},
    "fireworks": {"input": 0.0008, "output": 0.0012},
    "openrouter": {"input": 0.0020, "output": 0.0060},
    "ollama": {"input": 0.0, "output": 0.0},
    "custom": {"input": 0.0, "output": 0.0},
}


class ProviderRouter:
    """Routes model requests to the correct provider using BYOK config.

    Example:
        >>> router = ProviderRouter(config)
        >>> sel = router.resolve_provider(role="primary")
        >>> sel.provider in {"anthropic", "openai", "openrouter", "ollama"}
        True
    """

    def __init__(
        self,
        config: ArchonConfig,
        cost_governor: CostGovernor | None = None,
        live_mode: bool = False,
        timeout_seconds: float = 45.0,
    ) -> None:
        self._config = config
        self._cost_governor = cost_governor
        self._live_mode = live_mode
        self._http = httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        """Close network resources used by the router."""

        await self._http.aclose()

    def resolve_provider(
        self,
        role: str,
        model_override: str | None = None,
        provider_override: str | None = None,
    ) -> ProviderSelection:
        """Resolve the effective provider+model for a role.

        Example:
            >>> selection = router.resolve_provider("vision")
            >>> selection.role
            'vision'
        """

        providers_to_try = self._provider_priority_chain(role, provider_override)
        missing_keys: list[str] = []

        for provider_name in providers_to_try:
            selection = self._try_provider(provider_name, role, model_override)
            if selection is not None:
                return selection
            env_name = PROVIDER_ENV_KEY.get(provider_name)
            if env_name:
                missing_keys.append(env_name)

        detail = ", ".join(sorted(set(missing_keys)))
        if detail:
            raise ProviderUnavailableError(
                f"No available provider for role '{role}'. Missing keys: {detail}"
            )
        raise ProviderUnavailableError(
            f"No available provider for role '{role}'. Check byok role config."
        )

    async def invoke(
        self,
        role: str,
        prompt: str,
        *,
        task_id: str | None = None,
        model_override: str | None = None,
        provider_override: str | None = None,
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        """Execute one LLM request and normalize the result.

        Example:
            >>> response = await router.invoke(role="fast", prompt="Summarize this")
            >>> isinstance(response.text, str)
            True
        """

        selection = self.resolve_provider(
            role=role,
            model_override=model_override,
            provider_override=provider_override,
        )

        if not self._live_mode:
            response = self._simulate_response(prompt, selection)
        elif selection.provider == "anthropic":
            response = await self._call_anthropic(selection, prompt, system_prompt)
        elif selection.provider == "gemini":
            response = await self._call_gemini(selection, prompt, system_prompt)
        else:
            response = await self._call_openai_compatible(selection, prompt, system_prompt)

        if task_id and self._cost_governor:
            self._cost_governor.add_cost(task_id=task_id, cost_usd=response.usage.cost_usd)
        return response

    def _provider_priority_chain(self, role: str, provider_override: str | None) -> list[str]:
        if provider_override:
            return [provider_override]

        byok = self._config.byok
        if role == "embedding":
            return ["ollama"]

        role_provider = getattr(byok, role, byok.primary)
        chain = [role_provider]

        if byok.fallback and byok.fallback not in chain:
            chain.append(byok.fallback)

        # Try custom endpoints that explicitly claim this role.
        for endpoint in byok.custom_endpoints:
            if role in endpoint.roles and endpoint.name not in chain:
                chain.append(endpoint.name)
        return chain

    def _try_provider(
        self, provider_name: str, role: str, model_override: str | None
    ) -> ProviderSelection | None:
        custom = next(
            (
                endpoint
                for endpoint in self._config.byok.custom_endpoints
                if endpoint.name == provider_name
            ),
            None,
        )
        if custom:
            model = model_override or (custom.models[0] if custom.models else "custom-model")
            return ProviderSelection(
                provider="custom",
                role=role,
                model=model,
                base_url=custom.base_url,
                api_key=custom.api_key,
                source="custom_endpoint",
                endpoint_name=custom.name,
            )

        provider = provider_name.lower()
        if provider not in SUPPORTED_PROVIDERS:
            return None

        base_url = self._resolve_base_url(provider)
        api_key = self._resolve_api_key(provider)
        if api_key is None:
            return None

        model = self._resolve_model(provider, role, model_override)
        return ProviderSelection(
            provider=provider,
            role=role,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )

    def _resolve_base_url(self, provider: str) -> str:
        byok = self._config.byok
        if provider == "ollama":
            return byok.ollama_base_url
        if provider == "openrouter":
            return byok.openrouter_base_url
        return DEFAULT_BASE_URL[provider]

    def _resolve_api_key(self, provider: str) -> str | None:
        if provider == "ollama":
            return os.environ.get("OLLAMA_API_KEY", "ollama")

        env_name = PROVIDER_ENV_KEY[provider]
        value = os.environ.get(env_name)
        if not value:
            return None
        return value

    def _resolve_model(self, provider: str, role: str, model_override: str | None) -> str:
        if model_override:
            return model_override

        byok = self._config.byok
        if provider == "ollama":
            if role == "embedding":
                return byok.ollama_embedding_model
            if role == "vision":
                return byok.ollama_vision_model

        if provider == "openrouter" and byok.openrouter_fallback_chain:
            return byok.openrouter_fallback_chain[0]

        role_models = DEFAULT_MODEL_BY_ROLE.get(provider, {})
        return role_models.get(role) or role_models.get("primary") or "unknown-model"

    def _simulate_response(self, prompt: str, selection: ProviderSelection) -> ProviderResponse:
        prompt_tokens = _estimate_tokens(prompt)
        completion_tokens = max(24, min(256, int(prompt_tokens * 0.6)))
        usage = self._usage_for(selection.provider, prompt_tokens, completion_tokens)
        preview = " ".join(prompt.split())[:180]
        text = (
            f"[simulated:{selection.provider}/{selection.model}] "
            f"{preview if preview else 'no prompt content'}"
        )
        return ProviderResponse(
            text=text,
            provider=selection.provider,
            model=selection.model,
            usage=usage,
            raw={"simulated": True, "source": selection.source},
        )

    async def _call_openai_compatible(
        self, selection: ProviderSelection, prompt: str, system_prompt: str | None
    ) -> ProviderResponse:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {"model": selection.model, "messages": messages}
        headers = {"Content-Type": "application/json"}
        if selection.api_key and selection.api_key.lower() != "none":
            headers["Authorization"] = f"Bearer {selection.api_key}"

        url = f"{selection.base_url.rstrip('/')}/chat/completions"
        res = await self._http.post(url, json=payload, headers=headers)
        if res.status_code >= 400:
            raise ProviderCallError(
                f"Provider call failed ({selection.provider}) with HTTP {res.status_code}."
            )

        data = res.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content", "")
        if isinstance(text, list):
            text = " ".join(part.get("text", "") for part in text if isinstance(part, dict)).strip()

        usage_data = data.get("usage") or {}
        prompt_tokens = int(usage_data.get("prompt_tokens") or _estimate_tokens(prompt))
        completion_tokens = int(usage_data.get("completion_tokens") or _estimate_tokens(text))
        usage = self._usage_for(selection.provider, prompt_tokens, completion_tokens)
        return ProviderResponse(
            text=text,
            provider=selection.provider,
            model=selection.model,
            usage=usage,
            raw=data,
        )

    async def _call_anthropic(
        self, selection: ProviderSelection, prompt: str, system_prompt: str | None
    ) -> ProviderResponse:
        headers = {
            "x-api-key": selection.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": selection.model,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt

        url = f"{selection.base_url.rstrip('/')}/v1/messages"
        res = await self._http.post(url, json=payload, headers=headers)
        if res.status_code >= 400:
            raise ProviderCallError(f"Anthropic call failed with HTTP {res.status_code}.")

        data = res.json()
        parts = data.get("content") or []
        text = " ".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
        usage_data = data.get("usage") or {}
        prompt_tokens = int(usage_data.get("input_tokens") or _estimate_tokens(prompt))
        completion_tokens = int(usage_data.get("output_tokens") or _estimate_tokens(text))
        usage = self._usage_for("anthropic", prompt_tokens, completion_tokens)
        return ProviderResponse(
            text=text,
            provider="anthropic",
            model=selection.model,
            usage=usage,
            raw=data,
        )

    async def _call_gemini(
        self, selection: ProviderSelection, prompt: str, system_prompt: str | None
    ) -> ProviderResponse:
        base_url = selection.base_url.rstrip("/")
        if "/v1" in base_url:
            url = f"{base_url}/models/{selection.model}:generateContent"
        else:
            url = f"{base_url}/v1beta/models/{selection.model}:generateContent"
        url = f"{url}?key={selection.api_key}"

        parts = []
        if system_prompt:
            parts.append({"text": f"System: {system_prompt}"})
        parts.append({"text": prompt})
        payload = {"contents": [{"parts": parts}]}

        res = await self._http.post(url, json=payload)
        if res.status_code >= 400:
            raise ProviderCallError(f"Gemini call failed with HTTP {res.status_code}.")

        data = res.json()
        candidates = data.get("candidates") or []
        content = (candidates[0].get("content") if candidates else {}) or {}
        text_parts = content.get("parts") or []
        text = " ".join(
            part.get("text", "") for part in text_parts if isinstance(part, dict)
        ).strip()

        usage_data = data.get("usageMetadata") or {}
        prompt_tokens = int(usage_data.get("promptTokenCount") or _estimate_tokens(prompt))
        completion_tokens = int(usage_data.get("candidatesTokenCount") or _estimate_tokens(text))
        usage = self._usage_for("gemini", prompt_tokens, completion_tokens)
        return ProviderResponse(
            text=text,
            provider="gemini",
            model=selection.model,
            usage=usage,
            raw=data,
        )

    def _usage_for(
        self, provider: str, prompt_tokens: int, completion_tokens: int
    ) -> ProviderUsage:
        rates = TOKEN_PRICE_PER_1K.get(provider, TOKEN_PRICE_PER_1K["custom"])
        cost_usd = ((prompt_tokens * rates["input"]) + (completion_tokens * rates["output"])) / 1000
        return ProviderUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=round(cost_usd, 6),
        )


def _estimate_tokens(text: str) -> int:
    if not text:
        return 1
    # Fast approximation for cost governance when token data is unavailable.
    return max(1, int(math.ceil(len(text) / 4)))
