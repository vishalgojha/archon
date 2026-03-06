"""Push notification primitives and backend adapters (FCM/APNs)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from archon.core.approval_gate import ApprovalGate, EventSink
from archon.notifications.deeplink import DeepLinkRouter
from archon.notifications.device_registry import DeviceRegistry, DeviceToken

try:  # pragma: no cover - optional dependency
    import jwt
except Exception:  # pragma: no cover - optional dependency
    jwt = None  # type: ignore[assignment]


@dataclass(slots=True, frozen=True)
class Notification:
    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)
    badge: int | None = None
    sound: str | None = "default"


@dataclass(slots=True, frozen=True)
class PushResult:
    token_id: str
    platform: str
    success: bool
    status_code: int
    response_body: str
    provider: str
    stale: bool = False
    error: str | None = None


class FCMBackend:
    """FCM sender using v1 endpoint with OAuth, with legacy-key header fallback."""

    def __init__(
        self,
        *,
        project_id: str | None = None,
        server_key: str | None = None,
    ) -> None:
        self.project_id = (
            str(project_id or "").strip()
            or str(os.getenv("FCM_PROJECT_ID", "")).strip()
            or str(os.getenv("GOOGLE_CLOUD_PROJECT", "")).strip()
            or self._project_from_credentials_file()
        )
        self.server_key = str(server_key or os.getenv("FCM_SERVER_KEY", "")).strip()

    def send(self, device_token: DeviceToken, notification: Notification) -> PushResult:
        if not self.project_id:
            return PushResult(
                token_id=device_token.token_id,
                platform=device_token.platform,
                success=False,
                status_code=0,
                response_body="",
                provider="fcm",
                error="missing_project_id",
            )

        access_token = self._oauth_access_token()
        headers = {"Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        elif self.server_key:
            headers["Authorization"] = f"key={self.server_key}"
        else:
            return PushResult(
                token_id=device_token.token_id,
                platform=device_token.platform,
                success=False,
                status_code=0,
                response_body="",
                provider="fcm",
                error="missing_fcm_credentials",
            )

        payload: dict[str, Any] = {
            "message": {
                "token": device_token.token,
                "notification": {
                    "title": notification.title,
                    "body": notification.body,
                },
                "data": _string_map(notification.data),
            }
        }

        try:
            response = httpx.post(
                f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send",
                headers=headers,
                json=payload,
                timeout=15.0,
            )
        except Exception as exc:
            return PushResult(
                token_id=device_token.token_id,
                platform=device_token.platform,
                success=False,
                status_code=0,
                response_body="",
                provider="fcm",
                error=str(exc),
            )

        body = _response_text(response)
        stale = int(response.status_code) == 404
        return PushResult(
            token_id=device_token.token_id,
            platform=device_token.platform,
            success=200 <= int(response.status_code) < 300,
            status_code=int(response.status_code),
            response_body=body,
            provider="fcm",
            stale=stale,
            error=None
            if 200 <= int(response.status_code) < 300
            else body or f"http_{response.status_code}",
        )

    def _oauth_access_token(self) -> str:
        # Prefers service-account creds when google-auth is available.
        credentials_path = str(os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")).strip()
        if not credentials_path:
            return ""
        try:  # pragma: no cover - depends on optional google-auth install
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/firebase.messaging"],
            )
            creds.refresh(Request())
            return str(getattr(creds, "token", "") or "").strip()
        except Exception:
            return ""

    def _project_from_credentials_file(self) -> str:
        credentials_path = str(os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")).strip()
        if not credentials_path:
            return ""
        try:
            with open(credentials_path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return ""
        return str(payload.get("project_id", "")).strip()


class APNsBackend:
    """APNs sender with ES256 JWT auth."""

    def __init__(
        self,
        *,
        key_id: str | None = None,
        team_id: str | None = None,
        key_file: str | None = None,
        bundle_id: str | None = None,
    ) -> None:
        self.key_id = str(key_id or os.getenv("APNS_KEY_ID", "")).strip()
        self.team_id = str(team_id or os.getenv("APNS_TEAM_ID", "")).strip()
        self.key_file = str(key_file or os.getenv("APNS_KEY_FILE", "")).strip()
        self.bundle_id = str(bundle_id or os.getenv("APNS_BUNDLE_ID", "com.archon.app")).strip()

    def endpoint_base(self) -> str:
        env = str(os.getenv("APNS_ENV", "production")).strip().lower()
        if env == "development":
            return "https://api.development.push.apple.com"
        return "https://api.push.apple.com"

    def send(self, device_token: DeviceToken, notification: Notification) -> PushResult:
        token = self._generate_jwt()
        headers = {
            "authorization": f"bearer {token}",
            "apns-topic": self.bundle_id,
            "apns-push-type": "alert",
            "apns-priority": "10",
            "content-type": "application/json",
        }
        aps: dict[str, Any] = {
            "alert": {
                "title": notification.title,
                "body": notification.body,
            },
            "sound": notification.sound or "default",
        }
        if notification.badge is not None:
            aps["badge"] = int(notification.badge)
        payload: dict[str, Any] = {"aps": aps}
        payload.update(_string_map(notification.data))

        try:
            response = httpx.post(
                f"{self.endpoint_base()}/3/device/{device_token.token}",
                headers=headers,
                json=payload,
                timeout=15.0,
            )
        except Exception as exc:
            return PushResult(
                token_id=device_token.token_id,
                platform=device_token.platform,
                success=False,
                status_code=0,
                response_body="",
                provider="apns",
                error=str(exc),
            )

        body = _response_text(response)
        stale = int(response.status_code) in {400, 404, 410}
        return PushResult(
            token_id=device_token.token_id,
            platform=device_token.platform,
            success=200 <= int(response.status_code) < 300,
            status_code=int(response.status_code),
            response_body=body,
            provider="apns",
            stale=stale,
            error=None
            if 200 <= int(response.status_code) < 300
            else body or f"http_{response.status_code}",
        )

    def _generate_jwt(self) -> str:
        now = int(time.time())
        header = {"alg": "ES256", "kid": self.key_id or "unknown"}
        payload = {"iss": self.team_id or "unknown", "iat": now}
        if jwt is not None and self.key_file:
            try:
                with open(self.key_file, encoding="utf-8") as handle:
                    private_key = handle.read()
                encoded = jwt.encode(payload, private_key, algorithm="ES256", headers=header)
                if isinstance(encoded, bytes):
                    return encoded.decode("utf-8")
                return str(encoded)
            except Exception:
                pass
        return f"{_b64url_json(header)}.{_b64url_json(payload)}.signature"


class PushNotifier:
    """Tenant-aware fanout helper that routes per-platform backend."""

    def __init__(
        self,
        registry: DeviceRegistry,
        *,
        fcm_backend: FCMBackend | None = None,
        apns_backend: APNsBackend | None = None,
        approval_gate: ApprovalGate | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.registry = registry
        self.fcm_backend = fcm_backend or FCMBackend()
        self.apns_backend = apns_backend or APNsBackend()
        self.approval_gate = approval_gate or ApprovalGate(auto_approve_in_test=True)
        self.event_sink = event_sink
        self._deeplink_router = DeepLinkRouter()

    def send(self, device_token: DeviceToken, notification: Notification) -> PushResult:
        backend = self._backend_for_device(device_token)
        if backend is None:
            return PushResult(
                token_id=device_token.token_id,
                platform=device_token.platform,
                success=False,
                status_code=0,
                response_body="",
                provider="unknown",
                error=f"unsupported_platform:{device_token.platform}",
            )
        result = backend.send(device_token, notification)
        if result.stale:
            self.registry.mark_stale(device_token.token_id)
        return result

    def send_to_tenant(self, tenant_id: str, notification: Notification) -> list[PushResult]:
        results: list[PushResult] = []
        for token in self.registry.get_tokens_for_tenant(tenant_id):
            results.append(self.send(token, notification))
        return results

    async def send_approval_request(
        self,
        tenant_id: str,
        action_id: str,
        action_name: str,
        gate_timeout_s: float,
    ) -> list[PushResult]:
        """Send approval push with deep-link and schedule one midpoint reminder."""

        payload = self._deeplink_router.build_approval_push_payload(
            tenant_id=str(tenant_id),
            action_id=str(action_id),
            action_name=str(action_name),
        )
        await self._gate_external_push(
            {
                "tenant_id": str(tenant_id),
                "action_id": str(action_id),
                "action_name": str(action_name),
                "gate_timeout_s": float(gate_timeout_s),
                "deep_link": payload.data.get("deep_link", ""),
            }
        )

        notification = Notification(
            title=payload.title,
            body=payload.body,
            data=dict(payload.data),
            badge=1,
            sound="default",
        )
        results = self.send_to_tenant(str(tenant_id), notification)

        reminder_delay = max(0.0, float(gate_timeout_s) * 0.5)
        if reminder_delay > 0:

            async def _send_reminder() -> None:
                await asyncio.sleep(reminder_delay)
                reminder_data = dict(payload.data)
                reminder_data["reminder"] = "true"
                reminder = Notification(
                    title="Approval reminder",
                    body=f"ARCHON still needs approval for {action_name}",
                    data=reminder_data,
                    badge=1,
                    sound="default",
                )
                self.send_to_tenant(str(tenant_id), reminder)

            asyncio.create_task(_send_reminder())

        return results

    def _backend_for_device(self, device_token: DeviceToken) -> FCMBackend | APNsBackend | None:
        platform = str(device_token.platform or "").strip().lower()
        if platform in {"android", "fcm"}:
            return self.fcm_backend
        if platform in {"ios", "apns"}:
            return self.apns_backend
        return None

    async def _gate_external_push(self, context: dict[str, Any]) -> None:
        action_id = f"push-{uuid.uuid4().hex[:12]}"
        gate_context = dict(context)
        if self.event_sink is not None:
            gate_context["event_sink"] = self.event_sink
        await self.approval_gate.check(
            action="external_api_call",
            context=gate_context,
            action_id=action_id,
        )


def _string_map(payload: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in (payload or {}).items():
        output[str(key)] = str(value)
    return output


def _response_text(response: httpx.Response) -> str:
    text = str(getattr(response, "text", "") or "").strip()
    if text:
        return text
    try:
        data = response.json()
    except Exception:
        return ""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=True)


def _b64url_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
