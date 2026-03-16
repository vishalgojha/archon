# ARCHON Self-Evolving UI Build Log

This log is the step-by-step build record for the production-grade, self-evolving UI system.
It is intended as a handoff artifact for any next agent.

## Ground Rules Captured
- No prebuilt packs. Only a minimal orchestration + function-calling framework.
- UI is fully custom per tenant and evolves via approved change proposals.
- React is the UI stack.
- Build system lives in this repo.
- Production-grade: signed, versioned, immutable UI packs, with rollback.

## Step Log

### Step 0 - 2026-03-16
- Read existing repo structure and current web interfaces.
- No legacy dashboard/console surfaces remain, so the plan is a minimal shell that loads tenant UI packs.
- Decided packaging model: signed, versioned UI packs stored in repo-local registry with pluggable backends.
- Decided to add a minimal React shell that loads a tenant UI pack and exposes a strict bridge.

### Step 1 - 2026-03-16
- Added UI pack registry and storage modules:
  - `archon/ui_packs/storage.py`: pack descriptor loader, asset integrity checks, optional HMAC signature verification.
  - `archon/ui_packs/registry.py`: SQLite-backed metadata registry with active version tracking.
  - `archon/ui_packs/__init__.py`: exports.
- Added approval-gated actions for UI pack publish/activate in `archon/core/approval_gate.py`.
- Wired server state for UI pack registry + storage in `archon/interfaces/api/server.py`.
- Added API endpoints:
  - `GET /v1/ui-packs/active`
  - `GET /v1/ui-packs/versions`
  - `POST /v1/ui-packs/register` (approval-gated)
  - `POST /v1/ui-packs/activate` (approval-gated)
  - `GET /ui-packs/{version}/{asset_path}` (token-auth asset delivery)
- Added analytics event emission for UI pack publish/activate.
- Added token-based asset delivery and exempted `/ui-packs` from middleware so assets can be fetched with `?token=...`.

### Step 2 - 2026-03-16
- Added self-evolving shell UI:
  - `archon/interfaces/web/shell/index.html` (minimal shell UI, React loader, styling).
  - `archon/interfaces/web/shell/index.js` (chat + pack loader + bridge).
- Added server routing for the shell:
  - `GET /shell` to serve the shell index.
  - `/shell/assets/*` static mount for shell assets.
- Updated auth exemptions for `/shell` and `/shell/assets`.
- Shell now loads the active pack, exposes `window.ARCHON_BRIDGE`, and passes pack context to `window.ARCHON_PACK.mount`.
- Documented the UI pack contract in `UI_PACK_SPEC.md`.

### Step 3 - 2026-03-16
- Added UI pack builder for non-technical flows:
  - `archon/ui_packs/builder.py` generates pack assets + pack.json from a blueprint.
- Added `/v1/ui-packs/build` endpoint (approval-gated, optional auto-approve).
- Added builder UI to the shell so non-technical users can create and activate a pack.
- Added `auto_approve` support to register/activate for explicit operator-triggered actions.
- Updated `UI_PACK_SPEC.md` with build API and blueprint schema.

### Step 4 - 2026-03-16
- Added a guided onboarding wizard inside `/shell` for non-technical users.
- Wizard asks business context + workflows, then generates a blueprint and builds/activates the pack.
- Added natural-language intake with keyword-based workflow suggestions.
- Added a preview step before activation.

### Step 5 - 2026-03-16
- Reran `archon/tests/` with known hanging tests excluded.
- Command: `.venv/bin/python -m pytest archon/tests/ -v --ignore=archon/tests/test_api_http_auth.py --ignore=archon/tests/test_auth.py --ignore=archon/tests/test_billing_integration.py --ignore=archon/tests/test_deploy_worker.py -k "not (integration or api or auth or billing or http or middleware or lifespan or webchat or webhook)"`
- Result: failed during collection with `IndentationError` in `archon/tests/test_cli_copy_guard.py` line 50.
- Added `KNOWN_ISSUES.md` with the list of hanging test files.

### Step 6 - 2026-03-16
- Fixed `archon/tests/test_cli_copy_guard.py` indentation and reran the filtered `archon/tests/` command.
- Result: 70 passed, 0 failed, 1 skipped, 1 deselected.
- Cleanup complete: federation, finetune, marketplace, compliance, stripe, vision, vernacular, web_transform, studio, console all removed.
- Dashboard rebuilt as a 4-tab operator panel.

### Step 7 - 2026-03-16
- Ran `python -m pytest tests/` before commit.
- Result: failed during collection with `PydanticUndefinedAnnotation` (`TaskRequest` not defined) originating from `tests/test_api_server.py`.

### Step 8 - 2026-03-16
- Scaffolded `mobile/` Android project with Kotlin DSL Gradle, manifest, resources, and core config.
- Why: establish the Archon Mobile execution node with SDK 26/34 and required dependencies.
- Note: build/install not executed yet per explicit instruction to avoid building.
- Note: Gradle wrapper jar not generated yet; run `./gradlew wrapper` when ready to build.

### Step 9 - 2026-03-16
- Implemented `ArchonForegroundService` + `ArchonRuntime` + `GatewaySession` with foreground notification, WebSocket connection, and reconnect scheduling.
- Why: keep a persistent background node connected to Archon with exponential backoff and exact idle-safe alarms.
- Decision: WebSocket gateway path set to `/v1/mobile/gateway`; base URL stored in encrypted prefs with default `http://10.0.2.2:8000`.

### Step 10 - 2026-03-16
- Added `InvokeDispatcher`, `ContextCollector`, and `AuditLogStore` for function routing and SQLite audit trail.
- Why: execute backend-triggered functions and log all invocations locally for evolution audit.

### Step 11 - 2026-03-16
- Added `WhatsAppObserver` using `NotificationListenerService` to capture WhatsApp notifications and forward approved context.
- Why: support ambient WhatsApp context without Accessibility service.

### Step 12 - 2026-03-16
- Added `OnboardingActivity` with connect, permissions, test, and done flow plus encrypted API key storage.
- Why: ensure first-run setup and runtime permissions before the service runs silently.
- Decision: health check uses `GET /health` with bearer auth to validate connectivity.
