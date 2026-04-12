# Archon Coder

**Localhost agentic desktop platform** — multi-session, persistent memory, CDP browser automation.
Built on Archon swarm patterns, wrapped in Tauri for a native desktop experience.
Runs on free/local AI (Ollama) or cloud Hetzner GPU servers (~€3–24/mo).

## What It Is

A desktop app (Tauri) where you type natural language and a swarm of agents writes code,
executes commands, manages files, and automates your browser — 100% locally with free AI.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Tauri Desktop App (Rust)                                │
│  ├── Session management (create, persist, resume)        │
│  ├── CDP bridge (Chrome DevTools Protocol)               │
│  ├── Native file/shell access (Tauri plugins)            │
│  ├── System tray + global shortcuts                      │
│  └── Python Sidecar (FastAPI, internal port 18765)       │
│      ├── SpawnDecider — routes goals to agents           │
│      ├── CoderAgent — writes code files                  │
│      ├── ShellAgent — executes commands                  │
│      ├── FileAgent — reads filesystem                    │
│      ├── BrowserAgent — CDP browser automation            │
│      ├── EvolutionEngine — SQLite persistent memory       │
│      └── ConsciousnessStream — event logging              │
├──────────────────────────────────────────────────────────┤
│  Svelte Frontend (Vite)                                  │
│  ├── Session sidebar (multi-session, new/resume)          │
│  ├── Terminal panel (command output)                     │
│  ├── Consciousness panel (agent thinking stream)          │
│  └── File tree panel                                     │
└──────────────────────────────────────────────────────────┘

Persistent Storage: ~/.archon-coder/
├── sessions/
│   ├── sess_001/
│   │   ├── session.json        (metadata)
│   │   ├── conversation.jsonl  (message history)
│   │   └── project/            (files written by agents)
│   └── sess_002/
├── memory/
│   └── memory.db               (SQLite — evolution engine)
│       ├── interactions        (all user commands + outcomes)
│       ├── spawn_patterns      (best agent combos per goal)
│       ├── skill_performance   (per-skill success rates)
│       ├── file_changes        (file create/modify history)
│       ├── user_preferences    (learned preferences)
│       └── consciousness_events (persisted agent events)
└── config.json                 (user config)
```

## Quick Start

### Prerequisites

1. **Rust** (for Tauri) — `rustup default stable`
2. **Node.js 18+** — for frontend build
3. **Python 3.10+** — for the sidecar
4. **Ollama** running locally — `ollama pull qwen2.5:3b && ollama serve`
5. (Optional) **Chrome with remote debugging** — for CDP browser automation

### Dev Mode

```bash
cd archon-coder

# Install frontend deps
npm install

# Install sidecar deps
pip install -r sidecar/requirements.txt

# Start Ollama (separate terminal)
ollama serve

# Start the Tauri dev app
npm run tauri:dev
```

### Build Distributable

```bash
npm run tauri:build
# Output: src-tauri/target/release/bundle/
```

### CDP Browser Automation

To enable full browser control, start Chrome with remote debugging:

```bash
# Windows
chrome.exe --remote-debugging-port=9222

# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222
```

Then use commands like:
```
> open github.com and search for "rust tauri"
> scrape the pricing table from this page
> login to my dashboard and download the report
```

## Multi-Session Workflow

Sessions are isolated workspaces with their own conversation history and (optionally) project directories.

```
/sessions new "React App" isolated    → Creates sandboxed project dir
/sessions new "Fix Bug" shared        → Opens existing workspace
/sessions                              → List all sessions
/sessions switch sess_1234567890      → Resume that session
```

**Isolated mode**: Each session gets its own `project/` directory — perfect for starting fresh projects.
**Shared mode**: Sessions share your current working directory — perfect for continuing work on existing codebases.

## Persistent Memory

The **EvolutionEngine** (SQLite) learns from your interactions:

- **Spawn patterns**: Tracks which agent combinations succeed for each goal type
- **Skill performance**: Measures each agent's success rate over time
- **File history**: Logs every file created/modified across sessions
- **User preferences**: Stores your coding style, favorite languages, etc.
- **Conversation archive**: Full message history per session, always resumable

Over time, the SpawnDecider gets smarter — it consults historical data to choose the right agents.

## Slash Commands

| Command | Description |
|---------|-------------|
| `<natural language>` | Agent swarm decides what to do |
| `/model ollama\|groq` | Switch AI provider |
| `/code <task>` | Force code generation |
| `/shell <cmd>` | Force shell execution |
| `/file <path>` | Read file or list directory |
| `/browse <url>` | Browser automation via CDP |
| `/cdp <js>` | Execute JS via CDP Runtime.evaluate |
| `/sessions` | List sessions |
| `/sessions new <name> [mode]` | Create session |
| `/sessions switch <id>` | Switch session |
| `/help` | Show all commands |

## Project Structure

```
archon-coder/
├── src/                          # Svelte frontend
│   ├── main.ts                   # Entry point
│   ├── App.svelte                # Root layout
│   ├── app.html                  # HTML shell
│   └── lib/components/
│       ├── TopBar.svelte          # Model switch, panel toggles
│       ├── SessionSidebar.svelte  # Session list + create modal
│       ├── TerminalPanel.svelte   # Command input + output
│       ├── ConsciousnessPanel.svelte  # Agent thinking stream
│       └── FileTreePanel.svelte   # File browser
├── src-tauri/                    # Rust backend
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   └── src/
│       ├── main.rs               # Tauri app + commands
│       ├── state.rs              # Shared app state
│       ├── sidecar.rs            # Python sidecar lifecycle
│       ├── session.rs            # Session management (Rust)
│       ├── cdp.rs                # Chrome DevTools Protocol bridge
│       └── memory.rs             # Config + consciousness queries
├── sidecar/                      # Python sidecar (FastAPI)
│   ├── main.py                   # FastAPI server
│   ├── requirements.txt
│   ├── agents/
│   │   ├── coder.py              # Code generation + file writing
│   │   ├── shell.py              # Shell command execution
│   │   ├── file_agent.py         # Filesystem read/list
│   │   └── browser.py            # CDP browser automation
│   ├── providers/
│   │   ├── ollama.py             # Local Ollama provider
│   │   └── groq.py               # Groq API fallback
│   ├── memory/
│   │   ├── evolution_engine.py   # SQLite persistent memory
│   │   └── session_manager.py    # Session CRUD + conversation log
│   ├── swarm_decider.py          # Pattern-based agent routing
│   └── consciousness_stream.py   # Event logging with narrative
├── package.json
├── vite.config.ts
└── tsconfig.json
```

## Inspired By

- **Archon** — Swarm orchestrator, SpawnDeciderAgent, Consciousness Stream, Evolution Engine
- **page-agent** (Alibaba) — In-page CDP browser automation
- **OpenCode** — Multi-session persistent memory patterns

## Hetzner Cloud Ollama — Free AI at Scale

For heavier models (14B–70B params) or when local Ollama isn't enough, deploy to Hetzner Cloud.

### Server Tiers

| Type | vCPU | RAM | Model | Cost/mo |
|------|------|-----|-------|---------|
| CAX11 (ARM) | 2 | 4GB | qwen2.5:3b | €3.29 |
| CCX23 | 4 | 24GB | qwen2.5:14b, deepseek-r1:14b | €23.47 |
| CCX33 | 8 | 32GB | qwen2.5:32b, llama3.1:70b-Q2 | €33.41 |
| GPU (optional) | — | — | Any model, fast inference | €50+ |

### Deploy with Terraform

```bash
cd deploy/hetzner

# Set your Hetzner API token
export HCLOUD_TOKEN="your-token-here"

# Deploy (24GB RAM, qwen2.5:14b, your domain with auto-HTTPS)
terraform init
terraform apply \
  -var="domain_name=ollama.yourdomain.com" \
  -var="basic_auth_pass=your-strong-password"

# Output: server IP, HTTPS URL, and connect command
```

### What Gets Provisioned

1. **Ubuntu 24.04** server with your chosen size
2. **Ollama** installed and auto-started
3. **Your model** pre-pulled (ready immediately)
4. **Caddy** reverse proxy with:
   - Auto-HTTPS (Let's Encrypt — zero config)
   - Basic auth protection
   - Streaming support for chat responses
   - Health checks
5. **Firewall** — only ports 22, 80, 443 open

### Connect Archon Coder

After deployment, configure in the app or via environment variables:

```bash
# Environment variables
export OLLAMA_BASE_URL=https://ollama.yourdomain.com
export OLLAMA_AUTH_USER=ollama
export OLLAMA_AUTH_PASS=your-password

# Or set in Archon Coder settings:
#   Ollama URL: https://ollama.yourdomain.com
#   Auth user:  ollama
#   Auth pass:  your-password
```

### Models That Fit 24GB RAM

| Model | Size | Quality |
|-------|------|---------|
| `qwen2.5:14b` | 9GB | Excellent for coding |
| `deepseek-r1:14b` | 9GB | Reasoning-focused |
| `llama3.1:8b` | 4.9GB | Fast, general purpose |
| `codestral:22b` | 13GB | Best for code generation |
| `mistral:7b` | 4.4GB | Lightweight, versatile |

Pull additional models after deployment:
```bash
ssh root@<server-ip>
ollama pull codestral:22b
```

## License

MIT
