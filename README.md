# ARCHON

Autonomous Recursive Cognitive Hierarchy Orchestration Network.

This repository bootstraps the ARCHON runtime with:

- A provider-agnostic BYOK router (cloud, local, OpenAI-compatible custom endpoints)
- Debate-mode orchestration core (orchestrator, debate engine, base agents, cost governor)
- FastAPI + WebSocket service entrypoint
- CLI + TUI control plane with config validation
- Memory, evolution, and UI pack shell support

## Quick Start

Prereqs: Python 3.11+ and git.

1. Pick one install path (recommended: installer).

Installer (recommended). Run the command that matches your shell:

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
- creates an isolated runtime under `%LOCALAPPDATA%\\Programs\\Archon` on Windows, `~/.local/share/archon` on Linux/WSL, or `~/Library/Application Support/Archon` on macOS
- writes `archon` and `archon-server` shims into the runtime `bin` directory
- avoids replacing the shared `archon.exe` in your system Python
- refreshes the current PowerShell session when run via `install.ps1`

Open a new shell after installation if you used `install.cmd` or `install.sh`; `install.ps1` updates the current PowerShell session automatically.
You can re-run the same flow later with `archon install`.
Remove the dedicated runtime with `archon uninstall --yes`.

Repo-local virtualenv (no global install). Use this if you want to run from the repo only:

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

If you only want the runtime (no lint/test tooling), replace the last line with:

```powershell
pip install -r requirements.txt
```

```bash
pip install -r requirements.txt
```

2. Set at least one provider key in your environment (or use a local Ollama setup):

```powershell
$env:ANTHROPIC_API_KEY = "..."
$env:OPENAI_API_KEY = "..."
```

```bash
export ANTHROPIC_API_KEY="..."
export OPENAI_API_KEY="..."
```

3. Validate config:

```powershell
python -m archon.validate_config
```

```bash
python -m archon.validate_config
```

If you are just checking schema locally (no provider health calls), run:

```powershell
python -m archon.validate_config --dry-run --no-color
```

4. Start API server:

```powershell
archon ops serve
```

You can also run the dedicated server shim via `archon-server`.

## CLI

Once installed, ARCHON exposes a capability-oriented `archon` command surface.

Run `archon` with no subcommand to open the terminal control plane. The root view
renders drawers for:

- `core`
- `agents`
- `memory`
- `evolve`
- `providers`
- `ops`

That root surface is for capability discovery and navigation. The interactive chat
launcher lives under `archon core chat` or `archon agents tui` when you want the
transcript-driven terminal session.

The terminal session uses a markdown-first, low-noise layout (overview header +
streaming log + input line). Press `Ctrl+H` inside the session to toggle the
overview panel.

Example commands:

```powershell
archon
archon core
archon agents
archon memory
archon evolve
archon providers
archon ops
archon ops serve
archon ops health
archon agents task "Increase qualified leads in Indian pharmacy SMBs"
archon agents debate "Find the biggest bottleneck in our lead funnel"
archon agents tui
archon core chat
```

Useful entry points:

- `archon` shows the capability drawers and available control surfaces.
- `archon core chat` or `archon agents tui` opens the interactive terminal session.
- `archon ops serve` starts the API server.
- `archon ops health` checks the running server.
- `archon agents task` sends a task to the running API with tenant JWT auth.
- `archon agents debate` executes locally without going through HTTP.
- Some drawers intentionally expose staged placeholder commands before the full operator flow is wired.

6. Run tasks with explicit orchestration mode (debate-only today):

```json
POST /v1/tasks
{
  "goal": "Increase qualified leads in Indian pharmacy SMBs",
  "mode": "debate",
  "context": {
    "market": "India",
    "sector": "pharmacy"
  }
}
```

`mode="debate"` is the only supported orchestration mode right now, so you can omit it.

## Architecture (Implemented Runtime)

```text
archon/
├── core/
│   ├── orchestrator.py
│   ├── debate_engine.py
│   ├── swarm_router.py
│   ├── approval_gate.py
│   └── cost_governor.py
├── agents/
│   └── (debate agents)
├── providers/
├── memory/
├── evolution/
├── interfaces/api/
├── interfaces/cli/
├── interfaces/web/shell/
└── ui_packs/
```

Beyond the core orchestrator, provider, and API layers, the repo includes memory,
evolution, and the UI pack registry + shell for browser-based operator experiences.

## BYOK Guarantees

- Keys are loaded from `os.environ` only.
- Keys are never written into config files.
- Router never logs raw key values.
- Missing providers fail with actionable errors and fallback options.
