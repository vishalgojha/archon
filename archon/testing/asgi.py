"""ASGI test helpers that avoid Starlette's blocking TestClient.

This repo's dev/test environment can hang when using `fastapi.testclient.TestClient`
(it relies on AnyIO's thread portal). These helpers keep tests fully async and run
ASGI lifespan + HTTP/WebSocket traffic in-process.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from urllib.parse import urlencode, urlsplit
from starlette.websockets import WebSocketDisconnect


@asynccontextmanager
async def _direct_anyio_thread_calls_when_pytest() -> AsyncIterator[None]:
    """Work around hangs in AnyIO thread helpers under pytest.

    Some environments intermittently hang when AnyIO offloads file IO via
    `anyio.to_thread.run_sync()` (Starlette's `FileResponse`/`StaticFiles` use it).
    In tests, it's acceptable to run those calls synchronously to keep the suite
    deterministic.
    """

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        yield
        return

    try:
        import anyio.to_thread as to_thread
    except Exception:
        yield
        return

    original_run_sync = to_thread.run_sync

    async def run_sync(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return func(*args)

    to_thread.run_sync = run_sync  # type: ignore[assignment]
    try:
        yield
    finally:
        to_thread.run_sync = original_run_sync  # type: ignore[assignment]


@asynccontextmanager
async def lifespan(app: Any) -> AsyncIterator[None]:
    """Enter the app's lifespan context."""

    context = app.router.lifespan_context(app)
    async with _direct_anyio_thread_calls_when_pytest():
        async with context:
            yield


@dataclass(slots=True)
class ASGIResponse:
    """Minimal HTTP response wrapper for ASGI test requests."""

    status_code: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


async def request(
    app: Any,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
    content: bytes | str | None = None,
    base_url: str = "http://testserver",
) -> ASGIResponse:
    """Issue one in-process HTTP request against an ASGI app.

    This avoids `httpx.ASGITransport`, which can rely on AnyIO thread portals.
    """

    method = str(method).upper()
    raw_path = str(path or "/")
    if not raw_path.startswith("/"):
        raw_path = "/" + raw_path

    parsed = urlsplit(base_url)
    host = parsed.hostname or "testserver"
    port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
    scheme = parsed.scheme or "http"

    query = urlencode(params or {}, doseq=True)
    header_items: list[tuple[bytes, bytes]] = [(b"host", host.encode("ascii"))]
    for key, value in (headers or {}).items():
        header_items.append((key.lower().encode("ascii"), str(value).encode("utf-8")))

    if json_body is not None:
        body_bytes = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        header_items.append((b"content-type", b"application/json"))
    elif content is None:
        body_bytes = b""
    elif isinstance(content, bytes):
        body_bytes = content
    else:
        body_bytes = str(content).encode("utf-8")
    header_items.append((b"content-length", str(len(body_bytes)).encode("ascii")))

    receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    receive_queue.put_nowait({"type": "http.request", "body": body_bytes, "more_body": False})
    receive_queue.put_nowait({"type": "http.disconnect"})

    async def receive() -> dict[str, Any]:
        return await receive_queue.get()

    status_code = 500
    response_headers: dict[str, str] = {}
    chunks: list[bytes] = []

    async def send(message: dict[str, Any]) -> None:
        nonlocal status_code, response_headers
        msg_type = message.get("type")
        if msg_type == "http.response.start":
            status_code = int(message["status"])
            response_headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in message.get("headers") or []
            }
        elif msg_type == "http.response.body":
            chunks.append(message.get("body") or b"")
        else:
            raise AssertionError(f"Unexpected ASGI send message: {message!r}")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": scheme,
        "path": raw_path,
        "raw_path": raw_path.encode("utf-8"),
        "query_string": query.encode("utf-8"),
        "headers": header_items,
        "client": ("testclient", 123),
        "server": (host, port),
        "extensions": {},
    }

    async with _direct_anyio_thread_calls_when_pytest():
        await app(scope, receive, send)
    return ASGIResponse(status_code=status_code, headers=response_headers, body=b"".join(chunks))


@dataclass(slots=True)
class ASGIWebSocket:
    """Minimal async WebSocket session for ASGI apps."""

    _to_app: "asyncio.Queue[dict[str, Any]]"
    _from_app: "asyncio.Queue[dict[str, Any]]"

    async def send_text(self, text: str) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": str(text)})

    async def receive_text(self) -> str:
        message = await self._from_app.get()
        if message["type"] == "websocket.close":
            raise WebSocketDisconnect(code=int(message.get("code") or 1000))
        if message["type"] != "websocket.send":
            raise AssertionError(f"Unexpected websocket message: {message!r}")
        return str(message.get("text") or "")

    async def send_json(self, payload: Any) -> None:
        await self.send_text(json.dumps(payload, separators=(",", ":")))

    async def receive_json(self) -> Any:
        raw = await self.receive_text()
        return json.loads(raw)

    async def close(self, code: int = 1000) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": int(code)})


@asynccontextmanager
async def websocket_session(
    app: Any,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    query_string: str | None = None,
    base_url: str = "ws://testserver",
) -> AsyncIterator[ASGIWebSocket]:
    """Open an in-process WebSocket session to `path`.

    Raises `WebSocketDisconnect` if the server immediately closes during connect.
    """

    parsed = urlsplit(base_url)
    host = parsed.hostname or "testserver"
    port = int(parsed.port or 80)

    header_items: list[tuple[bytes, bytes]] = []
    for key, value in (headers or {}).items():
        header_items.append((key.lower().encode("ascii"), str(value).encode("utf-8")))

    to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    await to_app.put({"type": "websocket.connect"})

    async def receive() -> dict[str, Any]:
        return await to_app.get()

    async def send(message: dict[str, Any]) -> None:
        await from_app.put(message)

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": (query_string or "").encode("utf-8"),
        "headers": header_items,
        "client": ("testclient", 123),
        "server": (host, port),
        "subprotocols": [],
        "extensions": {},
    }

    async with _direct_anyio_thread_calls_when_pytest():
        task = asyncio.create_task(app(scope, receive, send))
        try:
            first = await from_app.get()
            if first["type"] == "websocket.close":
                raise WebSocketDisconnect(code=int(first.get("code") or 1000))
            if first["type"] != "websocket.accept":
                raise AssertionError(f"Expected websocket.accept, got {first!r}")

            ws = ASGIWebSocket(_to_app=to_app, _from_app=from_app)
            try:
                yield ws
            finally:
                await ws.close()
        finally:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
