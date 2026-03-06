"""LinkedIn API clients: profile research, connection requests, and DMs."""

from __future__ import annotations

import os
import time
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import httpx

from archon.agents.outreach.linkedin_types import (
    ConnectionResult,
    LinkedInProfile,
    NotConnectedError,
    SendResult,
    extract_elements,
    profile_from_payload,
    to_urn,
    truncate_note,
)
from archon.core.approval_gate import ApprovalDeniedError, ApprovalGate

_API_BASE = "https://api.linkedin.com/v2"


class ProfileResearcher:
    """LinkedIn profile and people search client with TTL caching."""

    def __init__(self, access_token: str | None = None, cache_ttl_seconds: int = 3600) -> None:
        """Create researcher. Example: `ProfileResearcher(access_token="token")`."""

        self.access_token = (access_token or os.getenv("LINKEDIN_ACCESS_TOKEN", "")).strip()
        self.cache_ttl_seconds = int(cache_ttl_seconds)
        self._cache: dict[str, tuple[float, LinkedInProfile]] = {}

    async def fetch_profile(self, linkedin_url_or_urn: str) -> LinkedInProfile:
        """Fetch one profile by URL or URN. Example: `await fetch_profile("urn:li:person:1")`."""

        urn = to_urn(linkedin_url_or_urn)
        cached = self._get_cached(urn)
        if cached is not None:
            return cached
        payload = await http_json(
            "GET", f"{_API_BASE}/people/{quote(urn, safe='')}", token=self.access_token
        )
        profile = profile_from_payload(payload, fallback_urn=urn)
        self._put_cache(profile)
        return profile

    async def fetch_connections(
        self, member_urn: str, max_results: int = 100
    ) -> list[LinkedInProfile]:
        """Fetch a member's connections. Example: `await fetch_connections("urn:li:person:1")`."""

        payload = await http_json(
            "GET",
            f"{_API_BASE}/connections",
            token=self.access_token,
            params={"q": "member", "member": to_urn(member_urn), "count": max(1, int(max_results))},
        )
        return self._profiles_from_elements(payload)

    async def search_people(
        self,
        keywords: str,
        company: str = "",
        title: str = "",
        location: str = "",
        max_results: int = 50,
    ) -> list[LinkedInProfile]:
        """Search people via `/v2/search?q=people`. Example: `await search_people("python")`."""

        params = {
            "q": "people",
            "keywords": keywords.strip(),
            "company": company.strip(),
            "title": title.strip(),
            "location": location.strip(),
            "count": max(1, int(max_results)),
        }
        payload = await http_json(
            "GET",
            f"{_API_BASE}/search",
            token=self.access_token,
            params={k: v for k, v in params.items() if v},
        )
        return self._profiles_from_elements(payload)

    def _profiles_from_elements(self, payload: dict[str, Any]) -> list[LinkedInProfile]:
        results: list[LinkedInProfile] = []
        for row in extract_elements(payload):
            urn = to_urn(str(row.get("urn") or row.get("entityUrn") or row.get("id") or ""))
            cached = self._get_cached(urn)
            if cached is not None:
                results.append(cached)
                continue
            profile = profile_from_payload(row, fallback_urn=urn)
            self._put_cache(profile)
            results.append(profile)
        return results

    def _get_cached(self, urn: str) -> LinkedInProfile | None:
        row = self._cache.get(urn)
        if row is None:
            return None
        expires_at, profile = row
        if expires_at <= time.time():
            self._cache.pop(urn, None)
            return None
        return profile

    def _put_cache(self, profile: LinkedInProfile) -> None:
        self._cache[profile.urn] = (time.time() + self.cache_ttl_seconds, profile)


class ConnectionAgent:
    """Connection request sender with mandatory approvals."""

    def __init__(self, approval_gate: ApprovalGate, access_token: str | None = None) -> None:
        """Create connection sender. Example: `ConnectionAgent(gate, "token")`."""

        self.approval_gate = approval_gate
        self.access_token = (access_token or os.getenv("LINKEDIN_ACCESS_TOKEN", "")).strip()

    async def send_connection_request(
        self,
        to_urn_value: str,
        note: str,
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> ConnectionResult:
        """Send one connection request. Example: `await send_connection_request("urn", "Hi")`."""

        target = to_urn(to_urn_value)
        trimmed_note = truncate_note(note, 300)
        try:
            await self.approval_gate.guard(
                action_type="send_message",
                payload={
                    "channel": "linkedin",
                    "operation": "connect",
                    "to": target,
                    "note": trimmed_note,
                },
                event_sink=event_sink,
                timeout_seconds=timeout_seconds,
            )
        except ApprovalDeniedError as exc:
            return ConnectionResult(target, f"denied:{exc.reason}", error=str(exc))
        response = await http_raw(
            "POST",
            f"{_API_BASE}/invitations",
            token=self.access_token,
            json={"recipient": target, "message": trimmed_note},
        )
        if response.status_code in {200, 201}:
            data = safe_json(response)
            return ConnectionResult(
                target,
                "sent",
                provider_request_id=str(data.get("id") or data.get("requestId") or "") or None,
            )
        return ConnectionResult(
            target, "failed", error=f"HTTP {response.status_code}: {response.text}"
        )

    async def check_connection_status(self, to_urn_value: str) -> str:
        """Check status. Returns `connected|pending|none`."""

        target = to_urn(to_urn_value)
        response = await http_raw(
            "GET",
            f"{_API_BASE}/connections/{quote(target, safe='')}",
            token=self.access_token,
        )
        if response.status_code != 200:
            return "none"
        value = str(safe_json(response).get("status", "")).strip().lower()
        return value if value in {"connected", "pending"} else "none"


class MessageAgent:
    """Direct-message sender with connection pre-check and approvals."""

    def __init__(
        self,
        approval_gate: ApprovalGate,
        access_token: str | None = None,
        status_checker: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        """Create message sender. Example: `MessageAgent(gate, "token")`."""

        self.approval_gate = approval_gate
        self.access_token = (access_token or os.getenv("LINKEDIN_ACCESS_TOKEN", "")).strip()
        self._status_checker = status_checker

    async def send_dm(
        self,
        to_urn_value: str,
        body: str,
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> SendResult:
        """Send one direct message. Example: `await send_dm("urn", "Hi")`."""

        target = to_urn(to_urn_value)
        status = await self.check_connection_status(target)
        if status != "connected":
            raise NotConnectedError(target)
        try:
            await self.approval_gate.guard(
                action_type="send_message",
                payload={
                    "channel": "linkedin",
                    "operation": "dm",
                    "to": target,
                    "body_preview": body[:200],
                },
                event_sink=event_sink,
                timeout_seconds=timeout_seconds,
            )
        except ApprovalDeniedError as exc:
            return SendResult(target, f"denied:{exc.reason}", error=str(exc))
        response = await http_raw(
            "POST",
            f"{_API_BASE}/messages",
            token=self.access_token,
            json={"recipients": [target], "body": body},
        )
        if response.status_code in {200, 201}:
            data = safe_json(response)
            return SendResult(target, "sent", provider_message_id=str(data.get("id") or "") or None)
        return SendResult(target, "failed", error=f"HTTP {response.status_code}: {response.text}")

    async def check_connection_status(self, to_urn_value: str) -> str:
        """Check status. Returns `connected|pending|none`."""

        target = to_urn(to_urn_value)
        if self._status_checker is not None:
            return await self._status_checker(target)
        response = await http_raw(
            "GET",
            f"{_API_BASE}/connections/{quote(target, safe='')}",
            token=self.access_token,
        )
        if response.status_code != 200:
            return "none"
        value = str(safe_json(response).get("status", "")).strip().lower()
        return value if value in {"connected", "pending"} else "none"


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def http_raw(
    method: str,
    url: str,
    *,
    token: str,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=20.0) as client:
        return await client.request(method, url, headers=headers(token), params=params, json=json)


async def http_json(
    method: str, url: str, *, token: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = await http_raw(method, url, token=token, params=params)
    return safe_json(response) if response.status_code == 200 else {}


def safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
