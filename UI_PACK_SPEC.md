# ARCHON UI Pack Specification

This document defines the production UI pack contract for the self-evolving ARCHON shell.

## Goals
- No prebuilt packs shipped by ARCHON.
- Packs are tenant-owned, versioned, and immutable.
- Packs are loaded by the shell with a strict bridge API.
- All pack publishes and activations require ApprovalGate.

## Pack Layout
- Root directory: `ARCHON_UI_PACK_ROOT` (default: `ui_packs`)
- Per-tenant version: `ui_packs/{tenant_id}/{version}/`
- Required file: `pack.json`
- Assets: any additional JS/CSS/images referenced by the pack

## pack.json Schema
Required fields:
- `schema_version`: integer, currently `1`
- `entrypoint`: string, entry JS path relative to the pack root
- `manifest`: object, pack-provided UI metadata
- `assets`: object of `{path: {sha256, content_type}}`

Optional fields:
- `metadata`: object with pack metadata
- `version`: string, if you want signature binding to version
- `signature`: string, hex-encoded HMAC-SHA256

Signature rules:
- If `ARCHON_UI_PACK_SIGNING_KEY` is set, `signature` is required.
- Signature payload is canonical JSON of:
  - `schema_version`, `entrypoint`, `manifest`, `assets`, `metadata`, and `version` if present.

## Asset Integrity
- Each asset entry must include `sha256` in hex.
- Asset verification runs during `POST /v1/ui-packs/register`.

## API Flow
Build pack:
1. `POST /v1/ui-packs/build` with `{ "version": "v1", "blueprint": {...} }`
2. ApprovalGate `ui_pack_build` required (set `auto_approve` for explicit operator triggers)

Register pack:
1. Build pack into `ui_packs/{tenant_id}/{version}/`
2. Call `POST /v1/ui-packs/register` with `{ "version": "v1" }`
3. ApprovalGate `ui_pack_publish` required

Activate pack:
1. Call `POST /v1/ui-packs/activate` with `{ "version": "v1" }`
2. ApprovalGate `ui_pack_activate` required

Load pack:
1. Shell calls `GET /v1/ui-packs/active`
2. Shell loads `/ui-packs/{version}/{entrypoint}?token=JWT`

## Runtime Pack Contract
Pack must export a global:
- `window.ARCHON_PACK.mount({ root, bridge, pack })`

The `mount` function can optionally return a cleanup function.

Shell-provided globals:
- `window.ARCHON_ASSET_BASE`
- `window.ARCHON_ASSET_TOKEN`

## Bridge API (initial)
- `bridge.resolveApiBase()`
- `bridge.getToken()`
- `bridge.setToken(token)`
- `bridge.apiFetch(path, options)`
- `bridge.callTask(goal, context, mode)`
- `bridge.listApprovals()`
- `bridge.assetUrl(path)`

## Notes
- Packs are loaded only if active for the tenant.
- Asset URLs require a `token` query parameter (tenant JWT).

## Blueprint Schema (Builder)
Minimal fields accepted by the builder:
- `title`: string
- `summary`: string
- `theme`: object (`accent`, `accentSoft`, `bg`, `panel`, `text`, `muted`, `font`)
- `drawers`: list of `{ id, title, type, description, items, columns }`
