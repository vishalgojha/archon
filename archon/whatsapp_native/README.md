# ARCHON WhatsApp Native

This package makes WhatsApp a first-class runtime inside ARCHON instead of assuming an external gateway.

## Pieces

- `native.py`: Python lifecycle manager + client for the local sidecar
- `sidecar/server.mjs`: Node/Baileys process
- `sidecar/package.json`: Node dependencies for the sidecar

## Install

From `C:\Users\visha\Documents\Playground\archon\archon\whatsapp_native\sidecar`:

```powershell
npm install
```

Required Node deps:

- `@whiskeysockets/baileys`
- `pino`

## Runtime

Default behavior:

- `ARCHON_BAILEYS_NATIVE=1`
- ARCHON autostarts the sidecar on first WhatsApp tool call
- session data is stored under the local Archon runtime directory

Important env vars:

- `ARCHON_BAILEYS_NATIVE`
- `ARCHON_BAILEYS_HOST`
- `ARCHON_BAILEYS_PORT`
- `ARCHON_BAILEYS_SESSION_DIR`
- `ARCHON_BAILEYS_API_KEY`
- `ARCHON_BAILEYS_NODE_BIN`

## Local API

- `GET /health`
- `GET /session/status`
- `GET /messages/inbox`
- `POST /messages/ack`
- `POST /messages/send`

## Pairing

Until the sidecar is paired:

- `GET /session/status` returns a `qr` field when available
- outbound sends will return a not-connected error

## Python Entry Points

- `archon.whatsapp_native.get_whatsapp_client()`
- `archon.interfaces.whatsapp.WhatsAppInterface.drain_native_inbox()`
