# ARCHON Architecture

## Overview

ARCHON (Autonomous Recursive Cognitive Hierarchy Orchestration Network) is a multi-agent orchestration system that coordinates LLM providers to execute complex tasks through debate-based reasoning.

## Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                     ARCHON Runtime                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Orchestrator │  │ Debate Engine │  │ Memory Store │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │               │
│         └─────────────────┼─────────────────┘               │
│                           │                                 │
│                    ┌──────┴──────┐                          │
│                    │ Swarm Router │                          │
│                    └──────┬──────┘                          │
│                           │                                 │
│                    ┌──────┴──────┐                          │
│                    │  Provider    │                          │
│                    │   Router     │                          │
│                    └──────┬──────┘                          │
│                           │                                 │
│         ┌─────────────────┼─────────────────┐               │
│         │                 │                 │               │
│    ┌────┴────┐      ┌────┴────┐      ┌────┴────┐          │
│    │Anthropic│      │ OpenAI  │      │  Ollama │          │
│    └─────────┘      └─────────┘      └─────────┘          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow

### Task Execution Flow

1. **Task Submission**: User submits a task via CLI or API
   ```
   POST /v1/tasks
   { "goal": "Analyze market trends", "mode": "debate" }
   ```

2. **Orchestration**: The `Orchestrator` coordinates the execution:
   - Selects appropriate skill (if enabled)
   - Initializes cost governor with budget
   - Configures provider routing

3. **Debate Execution**: The `DebateEngine` runs multi-round debate:
   - Spawns 6 agents (proponent, critic, fact-checker, etc.)
   - Each agent queries LLM via `ProviderRouter`
   - Arguments are exchanged and refined
   - Final synthesis is produced

4. **Memory Storage**: Results are stored in `MemoryStore` for future retrieval

5. **Audit Trail**: Execution metadata is logged to immutable audit trail

### Provider Selection Flow

```
User Task
    │
    ▼
┌─────────────────┐
│ Cost Governor   │ ← Check budget constraints
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Provider Router │ ← Check provider availability
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
Primary   Fallback
(Anthropic)  (OpenAI)
    │         │
    └────┬────┘
         │
         ▼
    LLM API Call
```

## Key Design Decisions

### 1. BYOK (Bring Your Own Key)
- API keys loaded from environment variables only
- Keys never written to config files
- Keys never logged
- Graceful degradation when providers unavailable

### 2. Debate Mode Orchestration
- Default mode for complex tasks
- Six-agent adversarial debate
- Increases reliability under uncertainty
- Configurable budget per task

### 3. Immutable Audit Trail
- All task executions logged
- Cryptographic hash chaining
- SQLite-based storage
- Compliance and debugging support

### 4. Provider Agnosticism
- Support for 9+ LLM providers
- Automatic fallback chain
- Unified response format
- Cost tracking across providers

## Directory Structure

```
archon/
├── core/                  # Core orchestration logic
│   ├── orchestrator.py    # Main task coordinator
│   ├── debate_engine.py   # Multi-agent debate
│   ├── approval_gate.py   # Human approval workflow
│   ├── cost_governor.py   # Budget management
│   └── memory_store.py    # Semantic memory
├── agents/                # Agent implementations
│   ├── base_agent.py      # Base agent class
│   ├── critic.py          # Critical analysis agent
│   └── ...
├── providers/             # LLM provider integrations
│   ├── router.py          # Provider selection logic
│   ├── base.py            # Abstract provider interface
│   └── types.py           # Type definitions
├── interfaces/            # External interfaces
│   ├── api/               # FastAPI REST API
│   ├── cli/               # Click CLI
│   └── web/               # Web dashboard
├── memory/                # Memory subsystem
├── evolution/             # Self-improvement system
├── skills/                # Skill definitions
└── ui_packs/              # UI component packs
```

## Extension Points

### Adding a New Provider

1. Create provider implementation in `archon/providers/`:
   ```python
   class MyProvider(BaseProvider):
       @classmethod
       def name(cls) -> ProviderName:
           return "myprovider"
       
       async def chat_completion(...) -> ProviderResponse:
           ...
   ```

2. Register in `router.py`:
   - Add to `PROVIDER_ENV_KEY`
   - Add to `DEFAULT_BASE_URL`
   - Add to `DEFAULT_MODEL_BY_ROLE`
   - Add to `TOKEN_PRICE_PER_1K`

### Adding a New Agent

1. Extend `BaseAgent`:
   ```python
   class MyAgent(BaseAgent):
       role = "my_role"
       
       async def execute(self, context: dict) -> str:
           ...
   ```

2. Register in `swarm_router.py`

### Adding a New Orchestration Mode

Extend `Orchestrator.execute()` with new mode handler:
```python
if mode == "pipeline":
    return await self._execute_pipeline(goal, context)
```

## Performance Considerations

- **Async I/O**: All provider calls are async
- **Connection Pooling**: HTTP client reused across requests
- **Rate Limiting**: SlowAPI integration for API endpoints
- **Caching**: Memory store for semantic retrieval
- **Budget Control**: Cost governor prevents overspending

## Security

- Environment variable key management
- Input validation on all API endpoints
- Audit trail for compliance
- Human approval gate for sensitive actions
