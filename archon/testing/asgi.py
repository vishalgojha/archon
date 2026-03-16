"""ASGI test helpers for async API tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the FastAPI lifespan for tests."""

    async with app.router.lifespan_context(app):
        yield


async def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    base_url: str = "http://testserver",
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    """Send an ASGI request to the app."""

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        return await client.request(method, path, json=json_body, headers=headers, params=params)
