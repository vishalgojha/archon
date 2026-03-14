# Archon EZ (Non‑Technical Mission Runner)

This folder adds a **wizard-style launcher** on top of the `archon` CLI so non‑technical users can:

- set up Archon once (config)
- start the local Archon server automatically
- create a “mission” (a goal + context)
- generate a structured plan (`plan.json`)
- execute it step‑by‑step with human confirmation
- generate “connector” outputs (email drafts, calendar invites, WhatsApp replies, etc.)

## Quick start (recommended)

1) Double‑click: `Archon EZ.cmd`
2) Pick **1) New mission** and follow the prompts.

## What gets created

Each mission becomes a folder under `missions/`:

- `brief.md` – your answers (goal, constraints, resources)
- `plan.json` – Archon’s plan in machine‑readable form
- `status.json` – which steps are done
- `history/` – raw Archon outputs for audit/debug
- `outputs/` – generated drafts and exports you can copy/paste

## Connectors (what “execution” means)

Archon EZ does **not** send emails or messages for you. “Execution” means generating ready‑to‑use artifacts in `outputs/`:

- **Email draft**: `.eml` + `.txt`
- **Calendar invite**: `.ics`
- **WhatsApp / Slack draft**: `.txt`
- **Browser checklist**: `.md`
- **CSV export**: `.csv`
- **Generic drafts**: `text_draft` / `markdown_draft`
- **File writes (safe)**: writes files into the mission folder only (requires typing a confirmation phrase)
- **Shell commands (optional)**: disabled by default; requires enabling “advanced mode” in the launcher and typing `RUN`

## If something fails

- If the server can’t start, run `archon serve --kill-port` in a terminal and re-try.
- If `plan.json` can’t be parsed, the raw output is still saved in `history/`.
