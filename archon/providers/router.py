"""Unified BYOK provider router for all ARCHON agents."""

from __future__ import annotations

import json
import math
import os
from typing import TYPE_CHECKING, Any

import httpx

from archon.config import SUPPORTED_PROVIDERS, ArchonConfig
from archon.core.cost_governor import CostGovernor
from archon.providers.types import ProviderResponse, ProviderSelection, ProviderUsage

if TYPE_CHECKING:
    from archon.agents.optimization import CostOptimizerAgent


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
        timeout_seconds: float = 45.0,
    ) -> None:
        self._config = config
        self._cost_governor = cost_governor
        self._http = httpx.AsyncClient(timeout=timeout_seconds)
        self._cost_optimizer: CostOptimizerAgent | None = None
        self._task_overrides: dict[str, dict[str, str | None]] = {}
        self._task_routing: dict[str, dict[str, Any]] = {}

    async def aclose(self) -> None:
        """Close network resources used by the router."""

        await self._http.aclose()

    def set_cost_optimizer(self, optimizer: "CostOptimizerAgent | None") -> None:
        """Attach a cost optimizer agent for budget-pressure downgrades.

        Example:
            >>> router.set_cost_optimizer(None)
        """

        self._cost_optimizer = optimizer

    def set_task_override(self, task_id: str, *, provider: str | None = None) -> None:
        if not provider:
            self._task_overrides.pop(task_id, None)
            return
        self._task_overrides[task_id] = {"provider": provider}

    def clear_task_override(self, task_id: str) -> None:
        self._task_overrides.pop(task_id, None)

    def clear_task_routing(self, task_id: str) -> None:
        self._task_routing.pop(task_id, None)

    def task_routing_snapshot(self, task_id: str) -> dict[str, Any]:
        entry = self._task_routing.get(task_id, {})
        providers = entry.get("providers") or set()
        if not isinstance(providers, set):
            providers = set(providers)
        return {
            "providers": sorted(providers),
            "fallback_used": bool(entry.get("fallback_used", False)),
            "preferred_provider": entry.get("preferred_provider"),
        }

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

        effective_provider_override = provider_override
        if task_id and effective_provider_override is None:
            override = self._task_overrides.get(task_id) or {}
            effective_provider_override = override.get("provider")
        selection = self.resolve_provider(
            role=role,
            model_override=model_override,
            provider_override=effective_provider_override,
        )
        self._record_task_routing(
            task_id=task_id,
            role=role,
            selection=selection,
            provider_override=effective_provider_override,
        )
        selection = self._optimize_selection_if_needed(task_id=task_id, selection=selection)

        if self._should_use_test_mode():
            response = self._test_response(selection=selection, prompt=prompt)
            self._record_usage(task_id=task_id, role=role, selection=selection, response=response)
            return response

        providers_to_try = self._provider_priority_chain(role, effective_provider_override)
        try_order: list[ProviderSelection] = []
        if selection.provider == "openrouter":
            openrouter_chain = self._openrouter_model_chain(role, model_override)
            if openrouter_chain:
                try_order.extend(openrouter_chain)
            else:
                try_order.append(selection)
        else:
            try_order.append(selection)
        for provider_name in providers_to_try:
            if provider_name == selection.provider:
                continue
            candidate = self._try_provider(provider_name, role, model_override)
            if candidate is not None:
                try_order.append(candidate)

        last_error: ProviderCallError | None = None
        for attempt in try_order:
            try:
                if attempt.provider == "anthropic":
                    response = await self._call_anthropic(attempt, prompt, system_prompt)
                elif attempt.provider == "gemini":
                    response = await self._call_gemini(attempt, prompt, system_prompt)
                else:
                    response = await self._call_openai_compatible(attempt, prompt, system_prompt)
            except ProviderCallError as exc:
                last_error = exc
                continue

            if attempt.provider != selection.provider:
                self._record_task_routing(
                    task_id=task_id,
                    role=role,
                    selection=attempt,
                    provider_override=effective_provider_override,
                )
            self._record_usage(task_id=task_id, role=role, selection=attempt, response=response)
            return response

        if last_error is not None:
            raise last_error
        raise ProviderCallError(f"Provider call failed ({selection.provider}).")

    def _record_task_routing(
        self,
        *,
        task_id: str | None,
        role: str,
        selection: ProviderSelection,
        provider_override: str | None,
    ) -> None:
        if not task_id:
            return
        entry = self._task_routing.setdefault(
            task_id,
            {"providers": set(), "fallback_used": False, "preferred_provider": None},
        )
        providers = entry.get("providers")
        if not isinstance(providers, set):
            providers = set(providers or [])
            entry["providers"] = providers
        providers.add(selection.provider)
        preferred = entry.get("preferred_provider")
        if preferred is None:
            preferred = provider_override or getattr(
                self._config.byok, role, self._config.byok.primary
            )
            entry["preferred_provider"] = preferred
        expected = provider_override or preferred
        if expected and selection.provider != expected:
            entry["fallback_used"] = True

    async def invoke_multimodal(
        self,
        *,
        role: str,
        text: str,
        content_blocks: list[dict[str, Any]],
        task_id: str | None = None,
        model_override: str | None = None,
        provider_override: str | None = None,
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        """Execute one multimodal request through the configured BYOK provider.

        Example:
            >>> hasattr(ProviderRouter, "invoke_multimodal")
            True
        """

        effective_provider_override = provider_override
        if task_id and effective_provider_override is None:
            override = self._task_overrides.get(task_id) or {}
            effective_provider_override = override.get("provider")
        selection = self.resolve_provider(
            role=role,
            model_override=model_override,
            provider_override=effective_provider_override,
        )
        self._record_task_routing(
            task_id=task_id,
            role=role,
            selection=selection,
            provider_override=effective_provider_override,
        )
        selection = self._optimize_selection_if_needed(task_id=task_id, selection=selection)

        if self._should_use_test_mode():
            response = self._test_response(selection=selection, prompt=text)
            self._record_usage(task_id=task_id, role=role, selection=selection, response=response)
            return response

        providers_to_try = self._provider_priority_chain(role, effective_provider_override)
        try_order: list[ProviderSelection] = []
        if selection.provider == "openrouter":
            openrouter_chain = self._openrouter_model_chain(role, model_override)
            if openrouter_chain:
                try_order.extend(openrouter_chain)
            else:
                try_order.append(selection)
        else:
            try_order.append(selection)
        for provider_name in providers_to_try:
            if provider_name == selection.provider:
                continue
            candidate = self._try_provider(provider_name, role, model_override)
            if candidate is not None:
                try_order.append(candidate)

        last_error: ProviderCallError | None = None
        for attempt in try_order:
            try:
                if attempt.provider == "anthropic":
                    response = await self._call_anthropic_multimodal(
                        attempt,
                        text=text,
                        content_blocks=content_blocks,
                        system_prompt=system_prompt,
                    )
                elif attempt.provider == "gemini":
                    response = await self._call_gemini_multimodal(
                        attempt,
                        text=text,
                        content_blocks=content_blocks,
                        system_prompt=system_prompt,
                    )
                else:
                    response = await self._call_openai_compatible_multimodal(
                        attempt,
                        text=text,
                        content_blocks=content_blocks,
                        system_prompt=system_prompt,
                    )
            except ProviderCallError as exc:
                last_error = exc
                continue

            if attempt.provider != selection.provider:
                self._record_task_routing(
                    task_id=task_id,
                    role=role,
                    selection=attempt,
                    provider_override=effective_provider_override,
                )
            self._record_usage(task_id=task_id, role=role, selection=attempt, response=response)
            return response

        if last_error is not None:
            raise last_error
        raise ProviderCallError(f"Provider call failed ({selection.provider}).")

    def record_task_feedback(self, task_id: str, *, quality_score: float) -> None:
        """Feed task-quality feedback back into the optimizer.

        Example:
            >>> router.record_task_feedback("task-1", quality_score=0.9)
        """

        if self._cost_optimizer is None:
            return
        self._cost_optimizer.record_task_feedback(task_id, quality_score=quality_score)

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

    def _openrouter_model_chain(
        self, role: str, model_override: str | None
    ) -> list[ProviderSelection]:
        byok = self._config.byok
        if not byok.openrouter_fallback_chain:
            return []
        if model_override and not byok.free_tier_first:
            return []

        chain: list[ProviderSelection] = []
        seen: set[str] = set()
        for model in byok.openrouter_fallback_chain:
            candidate = self._try_provider("openrouter", role, model)
            if candidate is None:
                continue
            key = f"{candidate.provider}:{candidate.model}"
            if key in seen:
                continue
            seen.add(key)
            chain.append(candidate)
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
            source="built_in",
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
            if role == "coding":
                return byok.ollama_coding_model
            if role == "fast":
                return byok.ollama_fast_model
            return byok.ollama_primary_model

        if provider == "openrouter" and byok.openrouter_fallback_chain:
            return byok.openrouter_fallback_chain[0]

        role_models = DEFAULT_MODEL_BY_ROLE.get(provider, {})
        return role_models.get(role) or role_models.get("primary") or "unknown-model"

    def _optimize_selection_if_needed(
        self,
        *,
        task_id: str | None,
        selection: ProviderSelection,
    ) -> ProviderSelection:
        if task_id is None or self._cost_optimizer is None or self._cost_governor is None:
            return selection

        try:
            snapshot = self._cost_governor.snapshot(task_id)
        except KeyError:
            return selection

        recommendation = self._cost_optimizer.recommend(
            role=selection.role,
            current_provider=selection.provider,
            current_model=selection.model,
            spend_snapshot=snapshot,
        )
        if recommendation is None:
            return selection

        candidate = self._try_provider(
            recommendation.to_provider,
            selection.role,
            recommendation.to_model,
        )
        if candidate is None:
            return selection
        if candidate.provider == selection.provider and candidate.model == selection.model:
            return selection

        self._cost_governor.record_optimization(
            task_id,
            {
                "role": selection.role,
                "from_provider": selection.provider,
                "from_model": selection.model,
                "to_provider": candidate.provider,
                "to_model": candidate.model,
                "spend_ratio": recommendation.spend_ratio,
                "estimated_savings_ratio": recommendation.estimated_savings_ratio,
                "reason": recommendation.reason,
                "sample_size": recommendation.sample_size,
            },
        )
        return candidate

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

    async def _call_anthropic_multimodal(
        self,
        selection: ProviderSelection,
        *,
        text: str,
        content_blocks: list[dict[str, Any]],
        system_prompt: str | None,
    ) -> ProviderResponse:
        headers = {
            "x-api-key": selection.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": selection.model,
            "max_tokens": 512,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": text}, *content_blocks],
                }
            ],
        }
        if system_prompt:
            payload["system"] = system_prompt
        url = f"{selection.base_url.rstrip('/')}/v1/messages"
        res = await self._http.post(url, json=payload, headers=headers)
        if res.status_code >= 400:
            raise ProviderCallError(
                f"Anthropic multimodal call failed with HTTP {res.status_code}."
            )
        data = res.json()
        parts = data.get("content") or []
        response_text = " ".join(
            part.get("text", "") for part in parts if isinstance(part, dict)
        ).strip()
        usage_data = data.get("usage") or {}
        prompt_tokens = int(usage_data.get("input_tokens") or _estimate_tokens(text))
        completion_tokens = int(usage_data.get("output_tokens") or _estimate_tokens(response_text))
        usage = self._usage_for("anthropic", prompt_tokens, completion_tokens)
        return ProviderResponse(
            text=response_text,
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

    async def _call_gemini_multimodal(
        self,
        selection: ProviderSelection,
        *,
        text: str,
        content_blocks: list[dict[str, Any]],
        system_prompt: str | None,
    ) -> ProviderResponse:
        base_url = selection.base_url.rstrip("/")
        if "/v1" in base_url:
            url = f"{base_url}/models/{selection.model}:generateContent"
        else:
            url = f"{base_url}/v1beta/models/{selection.model}:generateContent"
        url = f"{url}?key={selection.api_key}"
        parts: list[dict[str, Any]] = []
        if system_prompt:
            parts.append({"text": f"System: {system_prompt}"})
        parts.append({"text": text})
        for block in content_blocks:
            source = block.get("source") if isinstance(block, dict) else {}
            if not isinstance(source, dict):
                continue
            parts.append(
                {
                    "inline_data": {
                        "mime_type": source.get("media_type", "image/jpeg"),
                        "data": source.get("data", ""),
                    }
                }
            )
        res = await self._http.post(url, json={"contents": [{"parts": parts}]})
        if res.status_code >= 400:
            raise ProviderCallError(f"Gemini multimodal call failed with HTTP {res.status_code}.")
        data = res.json()
        candidates = data.get("candidates") or []
        content = (candidates[0].get("content") if candidates else {}) or {}
        text_parts = content.get("parts") or []
        response_text = " ".join(
            part.get("text", "") for part in text_parts if isinstance(part, dict)
        ).strip()
        usage_data = data.get("usageMetadata") or {}
        prompt_tokens = int(usage_data.get("promptTokenCount") or _estimate_tokens(text))
        completion_tokens = int(
            usage_data.get("candidatesTokenCount") or _estimate_tokens(response_text)
        )
        usage = self._usage_for("gemini", prompt_tokens, completion_tokens)
        return ProviderResponse(
            text=response_text,
            provider="gemini",
            model=selection.model,
            usage=usage,
            raw=data,
        )

    async def _call_openai_compatible_multimodal(
        self,
        selection: ProviderSelection,
        *,
        text: str,
        content_blocks: list[dict[str, Any]],
        system_prompt: str | None,
    ) -> ProviderResponse:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for block in content_blocks:
            source = block.get("source") if isinstance(block, dict) else {}
            if not isinstance(source, dict):
                continue
            media_type = str(source.get("media_type") or "image/jpeg")
            data = str(source.get("data") or "")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{data}"},
                }
            )
        messages.append({"role": "user", "content": content})

        payload = {"model": selection.model, "messages": messages}
        headers = {"Content-Type": "application/json"}
        if selection.api_key and selection.api_key.lower() != "none":
            headers["Authorization"] = f"Bearer {selection.api_key}"

        url = f"{selection.base_url.rstrip('/')}/chat/completions"
        res = await self._http.post(url, json=payload, headers=headers)
        if res.status_code >= 400:
            raise ProviderCallError(
                f"Provider multimodal call failed ({selection.provider}) with HTTP {res.status_code}."
            )

        data = res.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        response_text = message.get("content", "")
        if isinstance(response_text, list):
            response_text = " ".join(
                part.get("text", "") for part in response_text if isinstance(part, dict)
            ).strip()
        usage_data = data.get("usage") or {}
        prompt_tokens = int(usage_data.get("prompt_tokens") or _estimate_tokens(text))
        completion_tokens = int(
            usage_data.get("completion_tokens") or _estimate_tokens(response_text)
        )
        usage = self._usage_for(selection.provider, prompt_tokens, completion_tokens)
        return ProviderResponse(
            text=response_text,
            provider=selection.provider,
            model=selection.model,
            usage=usage,
            raw=data,
        )

    async def invoke_with_tools(
        self,
        *,
        role: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        task_id: str | None = None,
        model_override: str | None = None,
        provider_override: str | None = None,
        system_prompt: str | None = None,
        tool_style: str = "openai",
        max_tokens: int = 4096,
    ) -> ProviderResponse:
        """Execute one LLM request with tool calling support.

        Returns a ProviderResponse with tool_calls populated if the model requests tools.
        """
        from archon.providers.types import ProviderToolCall

        selection = self.resolve_provider(
            role=role,
            model_override=model_override,
            provider_override=provider_override,
        )
        self._record_task_routing(
            task_id=task_id,
            role=role,
            selection=selection,
            provider_override=provider_override,
        )

        # Build payload
        payload: dict[str, Any] = {
            "model": selection.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            if tool_style == "openai":
                payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if selection.api_key and selection.api_key.lower() != "none":
            headers["Authorization"] = f"Bearer {selection.api_key}"

        url = f"{selection.base_url.rstrip('/')}/chat/completions"
        res = await self._http.post(url, json=payload, headers=headers, timeout=120.0)

        if res.status_code >= 400:
            raise ProviderCallError(
                f"Provider tool call failed ({selection.provider}) with HTTP {res.status_code}: {res.text[:200]}"
            )

        data = res.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}

        # Extract text content
        response_text = message.get("content") or ""
        if isinstance(response_text, list):
            response_text = " ".join(
                part.get("text", "") for part in response_text if isinstance(part, dict)
            ).strip()

        # Extract tool calls
        tool_calls: list[ProviderToolCall] = []
        raw_tool_calls = message.get("tool_calls") or []
        for tc in raw_tool_calls:
            tc_id = tc.get("id", "")
            func = tc.get("function", {})
            func_name = func.get("name", "")
            func_args_str = func.get("arguments", "{}")
            try:
                func_args = json.loads(func_args_str) if isinstance(func_args_str, str) else func_args_str
            except json.JSONDecodeError:
                func_args = {"_raw": func_args_str}
            tool_calls.append(ProviderToolCall(
                call_id=tc_id,
                name=func_name,
                arguments=func_args,
            ))

        usage_data = data.get("usage") or {}
        prompt_tokens = int(usage_data.get("prompt_tokens", 0))
        completion_tokens = int(usage_data.get("completion_tokens", 0))
        usage = self._usage_for(selection.provider, prompt_tokens, completion_tokens)

        finish_reason = choice.get("finish_reason", "")

        return ProviderResponse(
            text=response_text,
            provider=selection.provider,
            model=selection.model,
            usage=usage,
            finish_reason=finish_reason,
            raw=data,
            tool_calls=tool_calls if tool_calls else None,
        )

    def _should_use_test_mode(self) -> bool:
        if os.environ.get("ARCHON_TEST_MODE"):
            return True
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            return False
        transport = getattr(self._http, "_transport", None)
        return not isinstance(transport, httpx.MockTransport)

    def _record_usage(
        self,
        *,
        task_id: str | None,
        role: str,
        selection: ProviderSelection,
        response: ProviderResponse,
    ) -> None:
        if task_id and self._cost_governor:
            self._cost_governor.add_cost(
                task_id=task_id,
                cost_usd=response.usage.cost_usd,
                provider=selection.provider,
                model=selection.model,
            )
        if task_id and self._cost_optimizer is not None:
            self._cost_optimizer.observe_selection(
                task_id,
                role=role,
                provider=selection.provider,
                model=selection.model,
                cost_usd=response.usage.cost_usd,
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

    def _test_response(self, *, selection: ProviderSelection, prompt: str) -> ProviderResponse:
        provider = selection.provider
        model = selection.model
        prompt_tokens = _estimate_tokens(prompt)
        completion_tokens = _estimate_tokens("Test response")
        usage = self._usage_for(provider, prompt_tokens, completion_tokens)
        return ProviderResponse(
            text="Test response",
            provider=provider,
            model=model,
            usage=usage,
            raw={"test_mode": True},
        )


def _estimate_tokens(text: str) -> int:
    if not text:
        return 1
    # Fast approximation for cost governance when token data is unavailable.
    return max(1, int(math.ceil(len(text) / 4)))
