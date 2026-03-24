# Contributing to ARCHON

Thank you for contributing to ARCHON! This guide covers how to extend the system with new providers, agents, and features.

## Development Setup

1. **Fork and clone the repository**
   ```bash
   git clone https://github.com/your-username/archon.git
   cd archon
   ```

2. **Create a virtual environment**
   ```bash
   make venv
   source .venv/bin/activate  # Linux/macOS
   .venv\Scripts\activate    # Windows
   ```

3. **Install development dependencies**
   ```bash
   make dev
   ```

4. **Verify setup**
   ```bash
   make check
   ```

## Adding a New Provider

### Step 1: Create Provider Implementation

Create a new file in `archon/providers/`:

```python
# archon/providers/myprovider.py
from __future__ import annotations

import httpx
from typing import Any

from archon.providers.base import BaseProvider
from archon.providers.types import ProviderName, ProviderResponse, ProviderRole, ProviderUsage


class MyProvider(BaseProvider):
    """Provider implementation for MyProvider API."""

    @classmethod
    def name(cls) -> ProviderName:
        return "myprovider"  # type: ignore

    @classmethod
    def default_base_url(cls) -> str:
        return "https://api.myprovider.com/v1"

    @classmethod
    def default_model(cls, role: ProviderRole) -> str:
        models = {
            "primary": "mypro-llm-large",
            "coding": "mypro-code",
            "vision": "mypro-vision",
            "fast": "mypro-fast",
        }
        return models.get(role, models["primary"])

    @classmethod
    def env_key(cls) -> str:
        return "MYPROVIDER_API_KEY"

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        client = await self.get_client()
        payload = self._build_messages_payload(messages, model or self.default_model("primary"), max_tokens, temperature)
        
        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        
        return self._parse_response(data)

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        # Pricing per 1K tokens
        input_price = 0.002  # $2 per 1M tokens
        output_price = 0.006  # $6 per 1M tokens
        
        return (prompt_tokens * input_price + completion_tokens * output_price) / 1000

    def _parse_response(self, raw: dict[str, Any]) -> ProviderResponse:
        choice = raw.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        
        usage = raw.get("usage", {})
        return ProviderResponse(
            content=content,
            model=raw.get("model", "unknown"),
            provider=self.name(),
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            finish_reason=choice.get("finish_reason"),
            raw_response=raw,
        )
```

### Step 2: Register Provider in Router

Update `archon/providers/router.py`:

```python
# Add to PROVIDER_ENV_KEY
PROVIDER_ENV_KEY = {
    ...
    "myprovider": "MYPROVIDER_API_KEY",
}

# Add to DEFAULT_BASE_URL
DEFAULT_BASE_URL = {
    ...
    "myprovider": "https://api.myprovider.com/v1",
}

# Add to DEFAULT_MODEL_BY_ROLE
DEFAULT_MODEL_BY_ROLE = {
    ...
    "myprovider": {
        "primary": "mypro-llm-large",
        "coding": "mypro-code",
        "vision": "mypro-vision",
        "fast": "mypro-fast",
    },
}

# Add to TOKEN_PRICE_PER_1K
TOKEN_PRICE_PER_1K = {
    ...
    "myprovider": {"input": 0.002, "output": 0.006},
}

# Add to SUPPORTED_PROVIDERS in config.py
SUPPORTED_PROVIDERS = {..., "myprovider"}
```

### Step 3: Add Provider Call Logic

In `router.py`, add the provider to the invoke method:

```python
async def invoke(self, role: str, prompt: str, ...) -> ProviderResponse:
    ...
    for attempt in try_order:
        try:
            if attempt.provider == "anthropic":
                response = await self._call_anthropic(...)
            elif attempt.provider == "myprovider":
                response = await self._call_myprovider(...)
            else:
                response = await self._call_openai_compatible(...)
        ...
```

### Step 4: Write Tests

```python
# tests/test_myprovider.py
import pytest
from archon.providers.myprovider import MyProvider


@pytest.mark.asyncio
async def test_myprovider_chat(mock_env_vars):
    provider = MyProvider(api_key="test-key")
    response = await provider.chat_completion(
        messages=[{"role": "user", "content": "Hello"}]
    )
    assert isinstance(response.content, str)
    assert response.provider == "myprovider"
```

## Adding a New Agent

### Step 1: Extend BaseAgent

```python
# archon/agents/my_agent.py
from __future__ import annotations

from archon.agents.base_agent import BaseAgent
from archon.providers import ProviderRouter


class MyAgent(BaseAgent):
    """Agent that performs my specific task."""

    role = "my_role"

    def __init__(self, provider_router: ProviderRouter) -> None:
        super().__init__(provider_router)
        # Initialize agent-specific state

    async def execute(self, context: dict) -> str:
        prompt = self._build_prompt(context)
        response = await self.provider_router.invoke(
            role="primary",
            prompt=prompt,
        )
        return self._parse_response(response.content, context)

    def _build_prompt(self, context: dict) -> str:
        # Build prompt from context
        return f"Analyze: {context.get('goal', '')}"

    def _parse_response(self, content: str, context: dict) -> str:
        # Parse and format response
        return content
```

### Step 2: Register in Swarm Router

```python
# archon/core/swarm_router.py
from archon.agents.my_agent import MyAgent

def build_debate_swarm(self) -> list[BaseAgent]:
    return [
        ...
        MyAgent(self.provider_router),
    ]
```

## Adding a New Orchestration Mode

Extend the `Orchestrator` class:

```python
# archon/core/orchestrator.py
async def execute(self, ..., mode: TaskMode = "debate", ...) -> OrchestrationResult:
    if mode == "debate":
        return await self._execute_debate(...)
    elif mode == "single":
        return await self._execute_single(...)
    elif mode == "pipeline":
        return await self._execute_pipeline(...)
    else:
        raise ValueError(f"Unsupported mode: {mode}")

async def _execute_single(self, goal: str, ...) -> OrchestrationResult:
    # Single agent execution
    response = await self.provider_router.invoke(
        role="primary",
        prompt=goal,
    )
    return OrchestrationResult(
        task_id=task_id,
        goal=goal,
        mode="single",
        final_answer=response.content,
        confidence=80,
        budget=budget_snapshot,
    )
```

## Testing Guidelines

### Unit Tests

```python
def test_something(sample_config):
    # Use fixtures from conftest.py
    orchestrator = Orchestrator(sample_config)
    ...
```

### Integration Tests

```python
@pytest.mark.integration
async def test_full_task(sample_config, mock_env_vars):
    # Test with real provider calls (mocked)
    ...
```

### Cleanup

Always use fixtures that clean up:

```python
def test_with_db(temp_db_path):
    # Database file is cleaned up automatically
    ...
```

## Code Style

- **Line length**: 100 characters
- **Type hints**: Required for all public APIs
- **Docstrings**: Google style for public functions
- **Imports**: Grouped (stdlib, third-party, local)

## Running Checks

```bash
# Run all checks
make check

# Individual checks
make lint        # ruff
make typecheck   # mypy
make test        # pytest
make format      # black
```

## Documentation

Update `docs/` when adding features:
- `docs/architecture.md` - Architecture changes
- `docs/providers.md` - New provider documentation
- `README.md` - User-facing changes

## Submitting Changes

1. Create a feature branch
2. Make changes with tests
3. Run `make check`
4. Submit pull request
