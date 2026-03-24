"""Webchat mounting helpers for the ARCHON API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles


def mount_webchat(app: FastAPI) -> FastAPI:
    """Mount the webchat UI onto the main API app.

    If a built webchat bundle exists, serve it as static assets; otherwise, fall
    back to a minimal placeholder page so imports and tests remain functional.
    """

    webchat_app = FastAPI(title="ARCHON Webchat")

    # Prefer a built bundle if present.
    static_root = Path(__file__).resolve().parents[2] / "studio" / "dist"
    if static_root.exists():
        webchat_app.mount("/", StaticFiles(directory=str(static_root), html=True), name="webchat")
    else:

        @webchat_app.get("/", response_class=HTMLResponse)
        async def webchat_placeholder() -> str:
            return (
                "<html><head><title>ARCHON Webchat</title></head>"
                "<body><h1>ARCHON Webchat</h1>"
                "<p>Webchat UI bundle not found. Build the studio app to enable it.</p>"
                "</body></html>"
            )

    app.mount("/webchat", webchat_app)
    return webchat_app
