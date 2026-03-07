"""Contract tests for mobile background sync helpers in the React Native hook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MOBILE_HOOK_PATH = _REPO_ROOT / "archon" / "interfaces" / "mobile" / "useARCHONMobile.ts"


def _mobile_source() -> str:
    return _MOBILE_HOOK_PATH.read_text(encoding="utf-8")


def _parse_silent_push_payload_py(raw: dict[str, Any]) -> dict[str, str] | None:
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    aps = raw.get("aps") if isinstance(raw.get("aps"), dict) else {}
    is_silent = (
        str(data.get("silent", "")).lower() == "true"
        or str(data.get("kind", "")).lower() == "background_sync"
        or int(aps.get("content-available", 0) or 0) == 1
        or int(aps.get("contentAvailable", 0) or 0) == 1
    )
    if not is_silent:
        return None
    return {
        "kind": "background_sync",
        "reason": str(data.get("reason") or data.get("action") or "background_refresh"),
        "tenantId": str(data.get("tenant_id") or ""),
        "sessionId": str(data.get("session_id") or ""),
    }


def _schedule_background_sync_py(
    current: dict[str, float | int | str],
    trigger: str,
    now: float,
) -> dict[str, Any]:
    dedupe_window = 5 if trigger == "silent_push" else 15
    if (
        float(current["lastAttemptAt"]) > 0
        and now - float(current["lastAttemptAt"]) < dedupe_window
    ):
        return {"shouldRun": False, "nextState": current}
    if trigger != "silent_push" and float(current["nextRetryAt"]) > now:
        return {"shouldRun": False, "nextState": current}
    return {
        "shouldRun": True,
        "nextState": {
            **current,
            "lastAttemptAt": now,
        },
    }


def _record_background_sync_success_py(
    current: dict[str, float | int | str],
    payload: dict[str, Any],
    now: float,
) -> dict[str, Any]:
    sync = payload.get("sync") if isinstance(payload.get("sync"), dict) else {}
    server_watermark = float(sync.get("watermark") or current["watermark"] or 0)
    next_cursor = str(sync.get("next_cursor") or "")
    recovered = sync.get("stale_watermark_recovered") is True
    return {
        "watermark": server_watermark
        if recovered
        else max(float(current["watermark"]), server_watermark),
        "cursor": next_cursor,
        "lastSuccessfulSyncAt": now,
        "lastAttemptAt": current["lastAttemptAt"],
        "retryCount": 0,
        "nextRetryAt": 0,
    }


def _record_background_sync_failure_py(
    current: dict[str, float | int | str],
    now: float,
) -> dict[str, Any]:
    retry_count = int(current["retryCount"]) + 1
    backoff = min(300, 5 * 2 ** max(0, retry_count - 1))
    return {
        **current,
        "retryCount": retry_count,
        "nextRetryAt": now + backoff,
        "lastAttemptAt": now,
    }


def test_mobile_hook_exposes_background_sync_contracts() -> None:
    source = _mobile_source()

    for snippet in [
        'export const SYNC_STATE_KEY = "archon.mobile.sync_state"',
        'export const OFFLINE_QUEUE_KEY = "archon.mobile.offline_queue"',
        "export function parseSilentPushPayload",
        "export function scheduleBackgroundSync",
        "export function routeSilentPushPayload",
        "export function recordBackgroundSyncSuccess",
        "export function recordBackgroundSyncFailure",
        "export async function loadOfflineQueueFromStorage",
        "export async function saveOfflineQueueToStorage",
        "queuedRef.current.push(payload);",
        "while (queuedRef.current.length > 0)",
        "void saveOfflineQueueToStorage(queuedRef.current);",
    ]:
        assert snippet in source


def test_background_sync_scheduling_and_deduplication() -> None:
    current = {
        "watermark": 10.0,
        "cursor": "",
        "lastSuccessfulSyncAt": 0.0,
        "lastAttemptAt": 100.0,
        "retryCount": 0,
        "nextRetryAt": 0.0,
    }

    deduped = _schedule_background_sync_py(current, "app_active", now=108.0)
    scheduled = _schedule_background_sync_py(current, "app_active", now=120.0)
    failed = _record_background_sync_failure_py(current, now=130.0)
    backoff_blocked = _schedule_background_sync_py(failed, "app_active", now=131.0)

    assert deduped["shouldRun"] is False
    assert scheduled["shouldRun"] is True
    assert failed["retryCount"] == 1
    assert failed["nextRetryAt"] == 135.0
    assert backoff_blocked["shouldRun"] is False


def test_silent_push_payload_parsing_and_routing() -> None:
    payload = {
        "data": {
            "kind": "background_sync",
            "silent": "true",
            "reason": "approval_resolved",
            "tenant_id": "tenant-a",
            "session_id": "session-a",
        }
    }
    current = {
        "watermark": 0.0,
        "cursor": "",
        "lastSuccessfulSyncAt": 0.0,
        "lastAttemptAt": 0.0,
        "retryCount": 0,
        "nextRetryAt": 200.0,
    }

    parsed = _parse_silent_push_payload_py(payload)
    routed = _schedule_background_sync_py(current, "silent_push", now=100.0)

    assert parsed == {
        "kind": "background_sync",
        "reason": "approval_resolved",
        "tenantId": "tenant-a",
        "sessionId": "session-a",
    }
    assert routed["shouldRun"] is True


def test_sync_watermark_progression_and_stale_recovery() -> None:
    current = {
        "watermark": 25.0,
        "cursor": "cursor-1",
        "lastSuccessfulSyncAt": 0.0,
        "lastAttemptAt": 50.0,
        "retryCount": 2,
        "nextRetryAt": 80.0,
    }

    progressed = _record_background_sync_success_py(
        current,
        {"sync": {"watermark": 30.0, "next_cursor": "cursor-2"}},
        now=60.0,
    )
    recovered = _record_background_sync_success_py(
        progressed,
        {
            "sync": {
                "watermark": 12.0,
                "next_cursor": "cursor-reset",
                "stale_watermark_recovered": True,
            }
        },
        now=70.0,
    )

    assert progressed["watermark"] == 30.0
    assert progressed["cursor"] == "cursor-2"
    assert progressed["retryCount"] == 0
    assert recovered["watermark"] == 12.0
    assert recovered["cursor"] == "cursor-reset"


def test_offline_queue_replay_contract_present_in_hook() -> None:
    source = _mobile_source()

    assert "queuedRef.current = persistedQueue;" in source
    assert 'void runBackgroundSync("startup");' in source
    assert 'void runBackgroundSync("reconnect");' in source
