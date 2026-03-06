"""Deep-link routing helpers for mobile push actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse


@dataclass(slots=True, frozen=True)
class DeepLink:
    scheme: str
    path: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ApprovalPushPayload:
    """Push payload wrapper compatible with FCM and APNs custom data fields."""

    title: str
    body: str
    data: dict[str, str]

    def to_fcm(self) -> dict[str, Any]:
        return {
            "notification": {"title": self.title, "body": self.body},
            "data": dict(self.data),
        }

    def to_apns(self) -> dict[str, Any]:
        return {
            "aps": {"alert": {"title": self.title, "body": self.body}, "sound": "default"},
            "custom_data": dict(self.data),
        }


class DeepLinkRouter:
    """Builds and parses ARCHON deep links."""

    def __init__(self, *, scheme: str = "archon") -> None:
        self.scheme = str(scheme).strip().replace("://", "") or "archon"

    def build_approval_link(self, action_id: str, action_name: str, tenant_id: str) -> DeepLink:
        if not str(action_id).strip():
            raise ValueError("action_id is required")
        if not str(action_name).strip():
            raise ValueError("action_name is required")
        if not str(tenant_id).strip():
            raise ValueError("tenant_id is required")
        return DeepLink(
            scheme=f"{self.scheme}://",
            path="approval",
            params={
                "action_id": str(action_id),
                "action": str(action_name),
                "tenant_id": str(tenant_id),
            },
        )

    def build_session_link(self, session_id: str) -> DeepLink:
        if not str(session_id).strip():
            raise ValueError("session_id is required")
        return DeepLink(
            scheme=f"{self.scheme}://",
            path="chat",
            params={"session_id": str(session_id)},
        )

    def encode(self, deeplink: DeepLink) -> str:
        scheme = str(deeplink.scheme or "").strip() or f"{self.scheme}://"
        if not scheme.endswith("://"):
            scheme = scheme.replace(":", "") + "://"
        query = urlencode({str(key): str(value) for key, value in deeplink.params.items()})
        suffix = f"?{query}" if query else ""
        return f"{scheme}{deeplink.path}{suffix}"

    def decode(self, uri: str) -> DeepLink:
        parsed = urlparse(str(uri or "").strip())
        if not parsed.scheme:
            raise ValueError("Deep link must include a scheme.")

        path = parsed.netloc or parsed.path.lstrip("/")
        params = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}
        link = DeepLink(scheme=f"{parsed.scheme}://", path=path, params=params)

        if path == "approval":
            required = {"action_id", "action", "tenant_id"}
            missing = [key for key in required if not params.get(key)]
            if missing:
                raise ValueError(f"Missing approval deep-link params: {', '.join(sorted(missing))}")
        if path == "chat" and not params.get("session_id"):
            raise ValueError("Missing chat deep-link params: session_id")
        return link

    def build_approval_push_payload(
        self,
        *,
        tenant_id: str,
        action_id: str,
        action_name: str,
    ) -> ApprovalPushPayload:
        deeplink_uri = self.encode(self.build_approval_link(action_id, action_name, tenant_id))
        data = {
            "action_id": str(action_id),
            "action": str(action_name),
            "tenant_id": str(tenant_id),
            "deep_link": deeplink_uri,
        }
        return ApprovalPushPayload(
            title="Approval required",
            body=f"ARCHON needs approval for {action_name}",
            data=data,
        )
