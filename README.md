# ARCHON

Autonomous Recursive Cognitive Hierarchy Orchestration Network.

This repository bootstraps the ARCHON runtime with:

- A provider-agnostic BYOK router (cloud, local, OpenAI-compatible custom endpoints)
- Phase 1 swarm core (orchestrator, debate engine, base agents, cost governor)
- FastAPI + WebSocket service entrypoint
- Config validation command and unit tests

## Quick Start

1. Create a virtual environment and install dependencies:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

2. Set at least one provider key in your environment:

```powershell
$env:ANTHROPIC_API_KEY = "..."
$env:OPENAI_API_KEY = "..."
```

3. Validate config:

```powershell
python -m archon.validate_config
```

4. Start API server:

```powershell
archon-server
```

5. Run tasks with explicit orchestration mode:

```json
POST /v1/tasks
{
  "goal": "Increase qualified leads in Indian pharmacy SMBs",
  "mode": "growth",
  "context": {
    "market": "India",
    "sector": "pharmacy"
  }
}
```

`mode="debate"` (default) runs the adversarial truth swarm.
`mode="growth"` runs the 7-agent sales/distribution growth swarm.

## Architecture (Implemented Bootstrap)

```text
archon/
├── core/
│   ├── orchestrator.py
│   ├── swarm_router.py
│   └── growth_router.py
├── agents/
│   ├── (debate agents)
│   └── growth/ (sales + distribution swarm)
├── providers/
└── interfaces/api/
```

The wider modules from your master plan (vision, web transform, evolution, federation)
are not fully implemented yet in this bootstrap.

## Sales & Distribution Layer (Growth Swarm Spec)

ARCHON now includes a scaffolded Growth Swarm designed for autonomous go-to-market execution.
This layer is strategy-first and guardrail-constrained: high autonomy, human approval on sensitive actions.

### Growth Swarm Agents

- `ProspectorAgent`: Detects lead intent signals from hiring, review text, and operational pain indicators.
- `ICPAgent`: Continuously rewrites ICP based on conversion, retention, and value realization data.
- `OutreachAgent`: Runs multi-channel campaigns (WhatsApp/SMS, email, LinkedIn, in-app, voice).
- `NurtureAgent`: Triggers contextual follow-ups based on in-product and engagement behaviors.
- `RevenueIntelAgent`: Diagnoses funnel bottlenecks and proposes interventions with measurable KPIs.
- `PartnerAgent`: Builds reseller/channel pipelines and manages onboarding + partner enablement.
- `ChurnDefenseAgent`: Detects churn risk early and executes retention playbooks before cancellation.

### Distribution Channels (Planned Operating Model)

- Viral embed loop via optional `Powered by ARCHON` referral surface.
- Federation-driven referrals across tenant networks.
- Marketplace operations (listing creation, optimization, and experiment loops).
- Multilingual content intelligence targeting automation pain-search queries.
- Community listening and trust-led engagement in relevant public forums.

### Revenue Guardrails

- Free tier for adoption; upgrades driven by observed value and activation readiness.
- Growth/Business/Enterprise expansion triggered by funnel evidence, not blanket promotions.
- Partner economics must remain transparent and auditable.
- Trust-critical markets require hybrid execution (agent autonomy + local human champions).

## BYOK Guarantees

- Keys are loaded from `os.environ` only.
- Keys are never written into config files.
- Router never logs raw key values.
- Missing providers fail with actionable errors and fallback options.
