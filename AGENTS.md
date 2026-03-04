## Working Agreements

- Run `pytest tests/` before every commit.
- All agent classes inherit `BaseAgent`.
- BYOK keys ONLY from `os.environ` (never hardcoded, never logged).
- Every agent action logged to immutable `audit_log`.
- Human approval gates enforced before any write, commit, or transaction.
- `CostGovernor` checked before spawning more than 3 agents.
- Run `python -m archon.validate_config` after any config change.
- Agent files stay under 300 lines (split if larger).
- All public methods have docstrings with input/output examples.
- Async throughout (`asyncio`) with no blocking calls on main thread.

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
