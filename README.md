# ARCHON

Autonomous Recursive Cognitive Hierarchy Orchestration Network.

This repository bootstraps the ARCHON runtime with:

- A provider-agnostic BYOK router (cloud, local, OpenAI-compatible custom endpoints)
- A persistent interactive chat runtime for terminal-driven operator sessions
- A WhatsApp-native path powered by a local Baileys sidecar
- FastAPI + WebSocket service entrypoint
- CLI + TUI control plane with config validation
- Swarm orchestration, memory, evolution, and UI pack shell support

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
archon ops serve
```

You can also run the dedicated server shim via `archon-server`.

## CLI

Once installed, ARCHON exposes a capability-oriented `archon` command surface.

### Enhanced TUI

Run `archon agents tui` to open the enhanced terminal dashboard with:

- **Tabbed interface** - Overview, Tasks, History, Log panels
- **Real-time progress bars** - Visual task tracking
- **Live budget display** - Spending analytics
- **Keyboard shortcuts** - Ctrl+1-4 for tabs, Ctrl+R refresh, Ctrl+Q quit
- **Modal dialogs** - Approval workflows
- **Notifications** - Success/error toasts

### Interactive Chat

`archon core chat` is now the primary terminal experience. Use it, or `archon agents tui`,
for a transcript-driven session where ARCHON responds turn by turn and can call tools as
needed.

The terminal session uses a markdown-first, low-noise layout (overview header +
streaming log + input line). Press `Ctrl+H` inside the session to toggle the
overview panel.

Recommended commands:

```powershell
archon
archon core
archon core chat
archon agents tui
archon ops serve
archon ops health
archon agents task "Increase qualified leads in Indian pharmacy SMBs"
archon agents swarm "Find the biggest bottleneck in our lead funnel"
```

### WhatsApp Native

ARCHON now has a WhatsApp-native path under `archon/whatsapp_native`.

What this means:

- the chat runtime can use WhatsApp tools without assuming a third-party gateway
- a local Node/Baileys sidecar is the default transport when `ARCHON_BAILEYS_NATIVE=1`
- the Python side owns lifecycle and the Node side owns the live WhatsApp session

Setup:

```powershell
cd archon\whatsapp_native\sidecar
npm install
```

See `archon/whatsapp_native/README.md` for the sidecar endpoints, pairing notes, and env vars.

Useful entry points:

- `archon` shows the capability drawers and available control surfaces.
- `archon core chat` opens the primary interactive terminal session.
- `archon agents tui` opens the same chat runtime inside the richer terminal UI.
- `archon ops serve` starts the API server.
- `archon ops health` checks the running server.
- `archon agents task` sends a task to the running API when you want request/response execution.
- `archon agents swarm` runs the local orchestration path directly.
- Some drawers intentionally expose staged placeholder commands before the full operator flow is wired.

6. Use the task API when you want a single request/response run:

```json
POST /v1/tasks
{
  "goal": "Increase qualified leads in Indian pharmacy SMBs",
  "mode": "swarm",
  "context": {
    "market": "India",
    "sector": "pharmacy"
  }
}
```

The task API remains swarm-oriented today. Interactive chat and WhatsApp-native sessions are
the primary operator-facing flows.

## Architecture (Implemented Runtime)

```text
archon/
├── core/
│   ├── orchestrator.py
│   ├── approval_gate.py
│   └── cost_governor.py
├── swarm/
│   ├── coordinator.py
│   ├── spawn_decider.py
│   ├── evolution.py
│   ├── memory.py
│   ├── agents/
│   └── tools/
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
