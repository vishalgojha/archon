## Working Agreements

- Run `pytest tests/` from the repo root before every commit.
- Run `python -m archon.validate_config` after any config change.
- BYOK keys ONLY from `os.environ` (never hardcoded, never logged).
- Human approval gates enforced before any write, commit, or transaction.
- `CostGovernor` checked before spawning more than 3 agents.
- Coverage floor: maintain **>= 80% per module** for any touched module family.
- Keep async paths non-blocking (`asyncio`) unless explicitly isolated.
- Any new external action MUST go through `ApprovalGate` first.

## Module Map & Test Locations

- Core API + auth + rate limits:
  - modules: `archon/interfaces/api/server.py`, `archon/interfaces/api/auth.py`, `archon/interfaces/api/rate_limit.py`
  - tests: `tests/test_api_server.py`, `archon/tests/test_api_http_auth.py`, `archon/tests/test_auth.py`
- Orchestration + cost governance:
  - modules: `archon/core/orchestrator.py`, `archon/core/debate_engine.py`, `archon/core/swarm_router.py`, `archon/core/approval_gate.py`, `archon/core/cost_governor.py`
  - tests: `tests/test_debate_engine.py`, `tests/test_cost_governor.py`, `tests/test_orchestrator_modes.py`, `tests/test_approval_gate.py`, `archon/tests/test_approval_gate.py`
- Providers + config validation:
  - modules: `archon/config.py`, `archon/providers/router.py`, `archon/validate_config.py`
  - tests: `tests/test_provider_router.py`, `tests/test_validate_config.py`, `archon/tests/test_provider_router.py`, `archon/tests/test_validate_config.py`
- Memory stack:
  - modules: `archon/memory/*.py`, `archon/core/memory_store.py`
  - tests: `archon/tests/test_memory.py`
- Evolution stack:
  - modules: `archon/evolution/*.py`
  - tests: `archon/tests/test_evolution.py`, `archon/tests/test_evolve_cli_helpers.py`
- CLI + TUI:
  - modules: `archon/archon_cli.py`, `archon/cli/**`, `archon/interfaces/cli/**`
  - tests: `tests/test_cli.py`, `tests/test_tui.py`, `tests/test_tui_onboarding.py`, `archon/tests/test_cli_drawers.py`, `archon/tests/test_cli_copy_guard.py`, `archon/tests/test_tui_input.py`
- UI packs + shell:
  - modules: `archon/ui_packs/**`, `archon/interfaces/web/shell/**`
  - tests: `archon/tests/test_ui_packs.py`
- Observability:
  - modules: `archon/observability/**`
  - tests: `archon/tests/test_observability.py`
