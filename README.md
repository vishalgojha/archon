# ARCHON

Autonomous Recursive Cognitive Hierarchy Orchestration Network.

This repository bootstraps the ARCHON runtime with:

- A provider-agnostic BYOK router (cloud, local, OpenAI-compatible custom endpoints)
- Phase 1 swarm core (orchestrator, debate engine, base agents, cost governor)
- FastAPI + WebSocket service entrypoint
- Config validation command and unit tests

## Quick Start

1. Install ARCHON globally for your user with the command that matches your shell:

Windows PowerShell:

```powershell
cd path\\to\\archon
.\install.ps1
```

Windows Command Prompt (`cmd.exe`):

```cmd
cd path\\to\\archon
install.cmd
```

WSL, Linux, or macOS:

```bash
cd /path/to/archon
./install.sh
```

Notes:

- Do not run `.\install.ps1` inside WSL or bash.
- Do not run `install.sh` without `./` from bash.
- Do not run `install.ps1` directly from `cmd.exe`; use `install.cmd` there.
- Use `.\install.ps1 --dev`, `install.cmd --dev`, or `./install.sh --dev` if you want the lint/test toolchain inside the dedicated ARCHON runtime.

The installer:

- uses your available `py -3` or `python` interpreter instead of hardcoding `py -3.11`
- creates an isolated runtime under `%LOCALAPPDATA%\Programs\Archon` on Windows, `~/.local/share/archon` on Linux/WSL, or `~/Library/Application Support/Archon` on macOS
- writes `archon` and `archon-server` shims into the runtime `bin` directory
- avoids replacing the shared `archon.exe` in your system Python
- refreshes the current PowerShell session when run via `install.ps1`

Open a new shell after installation if you used `install.cmd` or `install.sh`; `install.ps1` updates the current PowerShell session automatically.
You can re-run the same flow later with `archon install`.
Remove the dedicated runtime with `archon uninstall --yes`.

2. Manual development setup is still available if you want a repo-local virtual environment:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

3. Set at least one provider key in your environment:

```powershell
$env:ANTHROPIC_API_KEY = "..."
$env:OPENAI_API_KEY = "..."
```

```bash
export ANTHROPIC_API_KEY="..."
export OPENAI_API_KEY="..."
```

4. Validate config:

```powershell
python -m archon.validate_config
```

```bash
python -m archon.validate_config
```

5. Start API server:

```powershell
archon serve
```

You can still use `archon-server`, but `archon serve` is now the primary CLI entrypoint.

## CLI

Once installed, ARCHON exposes a capability-oriented `archon` command surface.

Run `archon` with no subcommand to open the terminal control plane. The root view
renders drawers for:

- `core`
- `agents`
- `growth`
- `vision`
- `web`
- `memory`
- `evolve`
- `federation`
- `providers`
- `marketplace`
- `studio`
- `ops`

That root surface is for capability discovery and navigation. The interactive chat
launcher is a separate path: use `archon tui` or `archon agents tui` when you want
the transcript-driven terminal session.

Example commands:

```powershell
archon
archon core
archon agents
archon providers
archon ops
archon ops serve
archon serve --kill-port
archon dashboard
archon studio open
archon agents task "Increase qualified leads in Indian pharmacy SMBs" --mode growth
archon agents tui
archon debate "Find the biggest bottleneck in our lead funnel"
archon token create --tenant-id demo --tier pro
```

Direct top-level shortcuts from the legacy CLI are still available for common flows,
including `archon serve`, `archon health`, `archon task`, `archon debate`, and
`archon tui`.

Useful entry points:

- `archon` shows the capability drawers and available control surfaces.
- `archon core chat`, `archon agents tui`, or `archon tui` opens the interactive terminal session.
- `archon ops serve` or `archon serve` starts the API server.
- `archon ops health` or `archon health` checks the running server.
- `archon agents task` or `archon task` sends a task to the running API with tenant JWT auth.
- `archon dashboard` opens Mission Control.
- `archon studio open` opens Studio in the browser.
- `archon debate` and `archon run` execute locally without going through HTTP.
- Some drawers intentionally expose staged placeholder commands before the full operator flow is wired.

6. Run tasks with explicit orchestration mode:

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

7. Outbound channels (approval-gated):

- `POST /v1/outbound/email`
- `POST /v1/outbound/webchat`

Both endpoints enforce JWT auth, per-tier rate limits, and `ApprovalGate` controls.
Use `auto_approve: true` only for explicit operator-triggered sends.

## Architecture (Implemented Runtime)

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

Beyond the core orchestrator, debate, growth, provider, and API layers, the current
repo also includes modules for vision, web intelligence, memory, evolution,
federation, marketplace, notifications, observability, mobile sync, and the Studio
/ Mission Control web surfaces. Some CLI drawers are still partially staged, but the
runtime modules are present in the codebase.

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
