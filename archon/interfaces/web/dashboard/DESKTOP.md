# ARCHON Desktop (Tauri wrapper)

This desktop wrapper uses **Tauri v1** and is meant to feel like a “real app”:
- The window loads the existing dashboard at `http://127.0.0.1:8000/dashboard/`.
- The desktop app auto-spawns `archon serve --port 8000` on launch and kills it on close.

## Recommended: run on Windows

Run from Windows (WebView2) to avoid Linux WebKitGTK dependency issues.

One-time setup (PowerShell):

```powershell
cd C:\Users\visha\archon
cargo install tauri-cli --locked --version "^1"
```

Run the desktop app (PowerShell):

```powershell
cd C:\Users\visha\archon\src-tauri
cargo tauri dev
```

Notes:
- Seeing `401 Unauthorized` for `GET /` is expected — the dashboard lives at `/dashboard/`.
- Studio is protected. Use the in-app `Dev Auth` button:
  - **Generate token** (requires `ARCHON_JWT_SECRET` in `C:\Users\visha\archon\.env` or system env), or
  - paste an existing Bearer JWT.

If the window keeps respawning / multiple blank windows:
- Close all `ARCHON.exe` / `archon-desktop.exe` instances in Task Manager, then retry `cargo tauri dev`.

## If you must use WSL/Linux

Ubuntu 24.04 ships WebKitGTK **4.1** packages, not 4.0, so Tauri v1 will fail with missing
`javascriptcoregtk-4.0.pc`.

Use one of:

- WSL Ubuntu **22.04** (Jammy), which provides the needed `*-4.0-dev` packages, or
- Upgrade the wrapper to Tauri v2 (not currently wired here).
