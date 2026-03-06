## Working Agreements

- Run `pytest tests/` before every commit.
- Run integration smoke suite `pytest tests archon/tests/test_integration.py` for cross-stack changes.
- All agent classes inherit `BaseAgent`.
- BYOK keys ONLY from `os.environ` (never hardcoded, never logged).
- Every agent action logged to immutable `audit_log`.
- Human approval gates enforced before any write, commit, or transaction.
- `CostGovernor` checked before spawning more than 3 agents.
- Run `python -m archon.validate_config` after any config change.
- Agent files stay under 300 lines (split if larger).
- All public methods have docstrings with input/output examples.
- Async throughout (`asyncio`) with no blocking calls on main thread.
- Coverage floor: maintain **>= 80% per module** for any touched module family.
- Any new action that sends data externally MUST go through `ApprovalGate` first.
- All agent memory reads/writes MUST use `tenant_ctx.memory_namespace` as key prefix.
- Community agent replies must never start with a product mention; always lead with direct user value.
- Content agent: every publishable piece must pass `SEOOptimizer` before entering any publishing queue.
- All outreach agents must enforce per-tenant configurable daily send limits with conservative defaults.
- Vernacular pipeline must never silently fall back to English; every fallback must log the reason explicitly.
- SOC2: all new PII-touching code must use `EncryptionLayer` for storage.
- Retention: every new entity type added must have a `RetentionRule` defined.
- Audit: every state-changing API endpoint must emit an `AnalyticsEvent`.

## Module Map & Test Locations

- Core API + auth + rate limits:
  - modules: `archon/interfaces/api/server.py`, `archon/interfaces/api/auth.py`, `archon/interfaces/api/rate_limit.py`
  - tests: `tests/test_api_server.py`, `archon/tests/test_integration.py`, `archon/tests/test_auth.py`
- Debate + growth orchestration:
  - modules: `archon/core/orchestrator.py`, `archon/core/debate_engine.py`, `archon/core/swarm_router.py`, `archon/core/growth_router.py`, `archon/agents/growth/*.py`
  - tests: `tests/test_orchestrator_modes.py`, `tests/test_growth_swarm.py`, `archon/tests/test_integration.py`
- Approval + cost governance:
  - modules: `archon/core/approval_gate.py`, `archon/core/cost_governor.py`
  - tests: `tests/test_approval_gate.py`, `tests/test_cost_governor.py`, `archon/tests/test_integration.py`
- Outbound channels (email/webchat):
  - modules: `archon/agents/outbound/email_agent.py`, `archon/agents/outbound/webchat_agent.py`
  - tests: `tests/test_email_agent.py`, `tests/test_webchat_agent.py`, `archon/tests/test_integration.py`
- Outreach channels (LinkedIn/SMS/Voice/WhatsApp):
  - modules: `archon/agents/outreach/*.py`
  - tests: `archon/tests/test_linkedin_agent.py`, `archon/tests/test_sms_voice_agents.py`, `archon/tests/test_whatsapp_agent.py`
- Memory stack:
  - modules: `archon/memory/*.py`
  - tests: `archon/tests/test_memory.py`
- Evolution stack:
  - modules: `archon/evolution/*.py`
  - tests: `archon/tests/test_evolution.py`
- Federation stack:
  - modules: `archon/federation/*.py`
  - tests: `archon/tests/test_federation.py`
- Vision stack:
  - modules: `archon/vision/*.py`
  - tests: `archon/tests/test_vision.py`
- Web intelligence stack:
  - modules: `archon/web/*.py`
  - tests: `archon/tests/test_web.py`
- WebChat auth/session/runtime:
  - modules: `archon/interfaces/webchat/*.py`
  - tests: `archon/tests/test_webchat.py`
- Web UI surfaces:
  - modules: `archon/interfaces/web/dashboard/**`, `archon/interfaces/web/console/**`
  - tests: `tests/test_api_server.py`, `archon/tests/test_integration.py`
- CLI + config validation:
  - modules: `archon/archon_cli.py`, `archon/validate_config.py`
  - tests: `archon/tests/test_cli.py`, `tests/test_validate_config.py`

## Sales & Distribution Layer (Codex Prompt Addendum)

- ARCHON growth operations are executed by a seven-agent Growth Swarm:
  `ProspectorAgent`, `ICPAgent`, `OutreachAgent`, `NurtureAgent`,
  `RevenueIntelAgent`, `PartnerAgent`, and `ChurnDefenseAgent`.
- Default distribution surfaces: viral embed loop, federation referrals, app marketplaces,
  multilingual content network, and community-driven trust channels.
- Human approval is mandatory before any irreversible external action:
  payouts, contractual commitments, price overrides, or policy exceptions.
- Outreach must be contextual, permission-aware, and local-language capable where needed.
- Agent-generated incentives and ROI claims must be auditable with explicit assumptions.
