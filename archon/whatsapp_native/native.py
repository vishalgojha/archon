"""Lifecycle and client helpers for the native Baileys sidecar."""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from archon.logging_utils import append_log, log_path

_DEFAULT_TIMEOUT_S = 20.0
_NATIVE_MANAGER: "NativeWhatsAppManager | None" = None


def _truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def native_whatsapp_enabled() -> bool:
    return _truthy(os.getenv("ARCHON_BAILEYS_NATIVE"), default=True)


def _runtime_root() -> Path:
    return log_path("archon-whatsapp-native.log").parent.parent


def _default_session_dir() -> Path:
    return _runtime_root() / "whatsapp-session"


def _native_sidecar_dir() -> Path:
    return Path(__file__).resolve().parent / "sidecar"


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = str(os.getenv("ARCHON_BAILEYS_API_KEY", "")).strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _timeout_s() -> float:
    return float(
        os.getenv("ARCHON_BAILEYS_TIMEOUT_S", str(_DEFAULT_TIMEOUT_S)) or _DEFAULT_TIMEOUT_S
    )


@dataclass(slots=True)
class RemoteWhatsAppClient:
    """Thin client for an externally managed WhatsApp gateway."""

    base_url: str

    async def status(self) -> dict[str, Any]:
        return await _request_json("GET", f"{self.base_url}/session/status")

    async def send_message(self, *, chat_id: str, text: str) -> dict[str, Any]:
        payload = {"chat_id": chat_id, "text": text}
        return await _request_json("POST", f"{self.base_url}/messages/send", payload=payload)

    async def fetch_inbox(self, *, limit: int = 20) -> dict[str, Any]:
        return await _request_json("GET", f"{self.base_url}/messages/inbox?limit={limit}")

    async def ack_messages(self, *, message_ids: list[str]) -> dict[str, Any]:
        payload = {"message_ids": list(message_ids)}
        return await _request_json("POST", f"{self.base_url}/messages/ack", payload=payload)


class NativeWhatsAppManager:
    """Starts and talks to the local Node/Baileys sidecar."""

    def __init__(self) -> None:
        self.host = str(os.getenv("ARCHON_BAILEYS_HOST", "127.0.0.1")).strip() or "127.0.0.1"
        self.port = int(os.getenv("ARCHON_BAILEYS_PORT", "3210") or 3210)
        self.node_bin = str(os.getenv("ARCHON_BAILEYS_NODE_BIN", "node")).strip() or "node"
        self.sidecar_dir = _native_sidecar_dir()
        self.session_dir = Path(
            os.getenv("ARCHON_BAILEYS_SESSION_DIR", str(_default_session_dir()))
        ).expanduser()
        self.log_file = log_path("archon-whatsapp-native.log")
        self._process: subprocess.Popen[str] | None = None
        self._log_handle: Any | None = None
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _process_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        with self._lock:
            if self._process_alive():
                return
            if not self.sidecar_dir.exists():
                raise FileNotFoundError(f"WhatsApp sidecar directory not found: {self.sidecar_dir}")

            self.session_dir.mkdir(parents=True, exist_ok=True)
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            if self._log_handle is None or getattr(self._log_handle, "closed", False):
                self._log_handle = self.log_file.open("a", encoding="utf-8")

            env = dict(os.environ)
            env["ARCHON_BAILEYS_HOST"] = self.host
            env["ARCHON_BAILEYS_PORT"] = str(self.port)
            env["ARCHON_BAILEYS_SESSION_DIR"] = str(self.session_dir)
            append_log("archon-whatsapp-native.log", f"starting_sidecar port={self.port}")
            self._process = subprocess.Popen(
                [self.node_bin, "server.mjs"],
                cwd=str(self.sidecar_dir),
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                env=env,
            )

    async def ensure_started(self, *, timeout_s: float = 20.0) -> None:
        if await self.is_healthy():
            return
        self.start()
        await self.wait_until_ready(timeout_s=timeout_s)

    async def wait_until_ready(self, *, timeout_s: float = 20.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if await self.is_healthy():
                return
            if self._process is not None and self._process.poll() is not None:
                raise RuntimeError(
                    f"WhatsApp sidecar exited early with code {self._process.returncode}."
                )
            await asyncio.sleep(0.4)
        raise TimeoutError("Timed out waiting for the WhatsApp sidecar to become healthy.")

    async def is_healthy(self) -> bool:
        try:
            payload = await _request_json("GET", f"{self.base_url}/health")
        except Exception:
            return False
        return bool(payload.get("ok", False))

    async def status(self) -> dict[str, Any]:
        await self.ensure_started()
        return await _request_json("GET", f"{self.base_url}/session/status")

    async def send_message(self, *, chat_id: str, text: str) -> dict[str, Any]:
        await self.ensure_started()
        payload = {"chat_id": chat_id, "text": text}
        return await _request_json("POST", f"{self.base_url}/messages/send", payload=payload)

    async def fetch_inbox(self, *, limit: int = 20) -> dict[str, Any]:
        await self.ensure_started()
        return await _request_json("GET", f"{self.base_url}/messages/inbox?limit={limit}")

    async def ack_messages(self, *, message_ids: list[str]) -> dict[str, Any]:
        await self.ensure_started()
        payload = {"message_ids": list(message_ids)}
        return await _request_json("POST", f"{self.base_url}/messages/ack", payload=payload)


def get_native_whatsapp_manager() -> NativeWhatsAppManager:
    global _NATIVE_MANAGER
    if _NATIVE_MANAGER is None:
        _NATIVE_MANAGER = NativeWhatsAppManager()
    return _NATIVE_MANAGER


def get_whatsapp_client() -> NativeWhatsAppManager | RemoteWhatsAppClient:
    if native_whatsapp_enabled():
        return get_native_whatsapp_manager()
    base_url = str(os.getenv("ARCHON_BAILEYS_BASE_URL", "http://127.0.0.1:3000")).rstrip("/")
    return RemoteWhatsAppClient(base_url=base_url)


async def _request_json(
    method: str, url: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_timeout_s(), trust_env=False) as client:
        response = await client.request(method, url, json=payload, headers=_headers())
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        return data
    return {"ok": response.status_code < 400, "data": data}
