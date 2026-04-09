# ARCHON

**Autonomous Recursive Cognitive Hierarchy Orchestration Network**

An AI-powered CLI assistant for India with 67 domain skills, local Ollama support, voice interaction, and browser automation.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Tests](https://img.shields.io/badge/Tests-178%20passing-brightgreen)
![Skills](https://img.shields.io/badge/Skills-67-orange)

## Features

| Feature | Description |
|---------|-------------|
| **67 India Skills** | Agriculture, legal, finance, healthcare, government schemes, startup funding |
| **Ollama Local** | Run with local models (gemma4, qwen3.5) - no API keys needed |
| **ElevenLabs Voice** | Text-to-speech with 11+ voices including Hindi |
| **6 Tools** | bash, read, write, glob, grep, list_dir |
| **TUI** | Interactive terminal with command palette (Ctrl+P), file browser (Ctrl+6) |
| **Cult UI** | 12 AI-first React components for web dashboard |
| **Page Agent** | Browser automation with natural language |

## Quick Start

```bash
# Clone and install
git clone https://github.com/vishalgojha/archon.git
cd archon
pip install -e ".[dev]"

# Configure for Ollama (local, free)
export OLLAMA_API_KEY="ollama"
export OLLAMA_BASE_URL="http://localhost:11434/v1"

# Or use cloud providers
export ANTHROPIC_API_KEY="..."
export OPENAI_API_KEY="..."

# Start chatting
archon core chat
```

## Commands

```bash
archon core chat              # Interactive TUI with local Ollama
archon providers ollama       # Check Ollama status and models
archon providers test         # Test all configured providers
python -m archon.validate_config  # Validate configuration
```

## 67 India Skills

### Agriculture (6)
kisan-advisory, soil-health, e-nam, pm-kisan, swachh-bharat, water-harvest

### Government (9)
passport, voter-id, pan-aadhaar, digilocker, e-district, ration-card, gas-subsidy, umang, govt-form

### Finance (8)
gst, msme-loan, msme-udyam, tax-itr, banking, epfo, upi-fraud, education-loan

### Healthcare (5)
healthcare-triage, ayushman-bharat, cowin-vaccine, jan-aushadhi, livestock-dairy

### Legal (5)
legal-aid, court-efile, land-record, property-verification, nalsa-legal

### Startup (4)
startup-india, startup-funding, women-entrepreneur, msme-udyam

### Services (7)
railway, vehicle-rto, telecom, insurance, water, electricity, e-shram

### Commerce (4)
customs, export, fssai, ondc

### Education (4)
scholarship, ncs-career, explain-theorem, national-scholarship

### More (15)
tourism-guide, irctc-tourism, digi-yatra, fisheries, cyber-crime, police-service, senior-citizen, disability, solar-adoption, weather-imd, ceir, pm-awas, pm-surya-ghar, browser-automation, voice-assistant

## Ollama Configuration

Archon works with local Ollama models:

```yaml
# config.archon.yaml
byok:
  primary: ollama
  coding: ollama
  fast: ollama
  ollama_base_url: http://localhost:11434/v1
  ollama_primary_model: gemma4:e4b    # 8B, good for coding
  ollama_fast_model: gemma4:e2b       # 5B, fast responses
```

**Recommended models for 8GB+ RAM:**
- `gemma4:e4b` — 8B, balanced (primary)
- `gemma4:e2b` — 5B, fast (secondary)
- `qwen3.5:latest` — 9.7B, coding

**Memory tip:** Close browser before running local models.

## Voice (ElevenLabs)

```bash
export ELEVENLABS_API_KEY="your-key"

# Voice is used automatically in TUI responses
archon core chat
```

## Architecture

```
archon/
├── core/           # Orchestrator, approval gate, cost governor
├── providers/      # Multi-provider router (Ollama, OpenAI, Anthropic)
├── tooling/        # Tools: bash, read, write, glob, grep
├── skills/         # 67 India-specific skills
├── voice/          # ElevenLabs TTS integration
├── interfaces/
│   ├── cli/        # TUI with Textual
│   ├── api/        # FastAPI server
│   └── web/cult-ui/# AI-first React components
└── tests/          # 178 tests
```

## BYOK Guarantees

- Keys loaded from `os.environ` only
- Keys never written to config files
- Router never logs raw key values
- Ollama works without any API key

## License

MIT
