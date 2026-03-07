"""Stripe webhook signature verification helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Callable

from archon.billing.models import WebhookEvent


def build_stripe_signature_header(
    payload: str,
    secret: str,
    *,
    timestamp: int | None = None,
) -> str:
    """Build a Stripe-compatible `Stripe-Signature` header for tests.

    Example:
        >>> header = build_stripe_signature_header('{"id":"evt_1","type":"invoice.paid"}', "whsec_test", timestamp=100)
        >>> header.startswith("t=100,v1=")
        True
    """

    issued_at = int(time.time() if timestamp is None else timestamp)
    signed_payload = f"{issued_at}.{payload}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={issued_at},v1={digest}"


class StripeWebhookVerifier:
    """Verify Stripe webhook signatures and parse event payloads."""

    def __init__(
        self,
        secret: str,
        *,
        tolerance_seconds: int = 300,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.secret = str(secret or "").strip()
        self.tolerance_seconds = int(tolerance_seconds)
        self._clock = clock or time.time

    def verify(self, payload: str, signature_header: str) -> WebhookEvent:
        """Verify one webhook payload and return normalized event metadata.

        Example:
            >>> verifier = StripeWebhookVerifier("whsec_test", tolerance_seconds=300, clock=lambda: 100.0)
            >>> header = build_stripe_signature_header('{"id":"evt_1","type":"invoice.paid"}', "whsec_test", timestamp=100)
            >>> verifier.verify('{"id":"evt_1","type":"invoice.paid"}', header).event_type
            'invoice.paid'
        """

        if not self.secret:
            raise ValueError("Stripe webhook secret is not configured.")
        timestamp, signatures = _parse_signature_header(signature_header)
        current = int(float(self._clock()))
        if abs(current - timestamp) > self.tolerance_seconds:
            raise ValueError("Webhook signature timestamp outside allowed tolerance.")

        expected = build_stripe_signature_header(payload, self.secret, timestamp=timestamp).split(
            ",v1=", 1
        )[1]
        if not any(hmac.compare_digest(expected, signature) for signature in signatures):
            raise ValueError("Webhook signature mismatch.")

        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise ValueError("Webhook payload must be a JSON object.")
        event_id = str(parsed.get("id", "")).strip()
        event_type = str(parsed.get("type", "")).strip()
        if not event_id or not event_type:
            raise ValueError("Webhook payload missing id/type.")
        created_at = float(parsed.get("created") or timestamp)
        return WebhookEvent(
            event_id=event_id,
            event_type=event_type,
            payload=parsed,
            created_at=created_at,
        )


def _parse_signature_header(signature_header: str) -> tuple[int, list[str]]:
    parts = [item.strip() for item in str(signature_header or "").split(",") if item.strip()]
    timestamp = 0
    signatures: list[str] = []
    for part in parts:
        key, _, value = part.partition("=")
        if key == "t":
            timestamp = int(value or "0")
        elif key == "v1" and value:
            signatures.append(value)
    if timestamp <= 0 or not signatures:
        raise ValueError("Invalid Stripe-Signature header.")
    return timestamp, signatures
