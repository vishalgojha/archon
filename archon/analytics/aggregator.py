"""Analytics aggregations computed from raw append-only events."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime, timezone
from datetime import time as time_cls
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class MetricResult:
    """Computed metric output row."""

    metric: str
    value: float
    period_start: float
    period_end: float
    tenant_id: str
    dimensions: dict[str, Any] = field(default_factory=dict)


class AnalyticsAggregator:
    """Tenant-isolated metrics computed over analytics event rows."""

    def __init__(self, path: str | Path = "archon_analytics.sqlite3") -> None:
        self.path = Path(path)

    def daily_active_sessions(self, tenant_id: str, date: str | date_cls | datetime) -> int:
        day = _coerce_date(date)
        start = _day_start_ts(day)
        end = start + 86400.0

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT session_id) AS count
                FROM analytics_events
                WHERE tenant_id = ?
                  AND timestamp >= ?
                  AND timestamp < ?
                  AND session_id IS NOT NULL
                  AND session_id != ''
                  AND event_type = 'session_started'
                """,
                (str(tenant_id), start, end),
            ).fetchone()
            count = int(row["count"]) if row else 0
            if count:
                return count

            fallback = conn.execute(
                """
                SELECT COUNT(DISTINCT session_id) AS count
                FROM analytics_events
                WHERE tenant_id = ?
                  AND timestamp >= ?
                  AND timestamp < ?
                  AND session_id IS NOT NULL
                  AND session_id != ''
                """,
                (str(tenant_id), start, end),
            ).fetchone()
            return int(fallback["count"]) if fallback else 0

    def cost_by_provider(self, tenant_id: str, start: Any, end: Any) -> dict[str, float]:
        start_ts, end_ts = self._coerce_window(start, end)
        rows = self._query_events(
            tenant_id=tenant_id,
            start_ts=start_ts,
            end_ts=end_ts,
            event_type="cost_incurred",
        )

        totals: dict[str, float] = {}
        for row in rows:
            props = row["properties"]
            provider = str(props.get("provider") or "unknown").strip().lower()
            if not provider:
                provider = "unknown"
            amount = float(props.get("cost_usd", 0.0) or 0.0)
            totals[provider] = round(totals.get(provider, 0.0) + amount, 6)
        return totals

    def approval_rate(self, tenant_id: str, start: Any, end: Any) -> float:
        start_ts, end_ts = self._coerce_window(start, end)
        with self._connect() as conn:
            granted = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM analytics_events
                WHERE tenant_id = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
                  AND event_type = 'approval_granted'
                """,
                (str(tenant_id), start_ts, end_ts),
            ).fetchone()
            denied = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM analytics_events
                WHERE tenant_id = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
                  AND event_type = 'approval_denied'
                """,
                (str(tenant_id), start_ts, end_ts),
            ).fetchone()

        granted_count = int(granted["count"]) if granted else 0
        denied_count = int(denied["count"]) if denied else 0
        total = granted_count + denied_count
        if total == 0:
            return 0.0
        return granted_count / float(total)

    def swarm_efficiency(self, tenant_id: str, start: Any, end: Any) -> float:
        """Average recruited agents per task; lower values are better."""

        start_ts, end_ts = self._coerce_window(start, end)
        rows = self._query_events(
            tenant_id=tenant_id,
            start_ts=start_ts,
            end_ts=end_ts,
            event_type="agent_recruited",
        )

        per_task: dict[str, int] = {}
        for row in rows:
            props = row["properties"]
            task_id = str(props.get("task_id") or row.get("session_id") or "").strip()
            if not task_id:
                continue
            per_task[task_id] = per_task.get(task_id, 0) + 1

        if not per_task:
            return 0.0
        return sum(per_task.values()) / float(len(per_task))

    def channel_conversion_rate(self, tenant_id: str, channel: str, start: Any, end: Any) -> float:
        """community_response_posted -> partner_conversion in same session."""

        start_ts, end_ts = self._coerce_window(start, end)
        normalized_channel = str(channel or "").strip().lower()

        rows = self._query_events(
            tenant_id=tenant_id,
            start_ts=start_ts,
            end_ts=end_ts,
            event_type=None,
        )

        posted_sessions: set[str] = set()
        converted_sessions: set[str] = set()
        for row in rows:
            event_type = row["event_type"]
            props = row["properties"]
            session_id = str(row.get("session_id") or props.get("session_id") or "").strip()
            if not session_id:
                continue

            row_channel = str(props.get("channel") or "").strip().lower()
            channel_match = not normalized_channel or row_channel == normalized_channel

            if event_type == "community_response_posted" and channel_match:
                posted_sessions.add(session_id)
                continue

            if event_type == "partner_conversion":
                # Allow conversion events without explicit channel if session links back.
                if channel_match or not row_channel:
                    converted_sessions.add(session_id)

        if not posted_sessions:
            return 0.0
        return len(posted_sessions & converted_sessions) / float(len(posted_sessions))

    def top_content_pieces(self, tenant_id: str, limit: int = 10) -> list[str]:
        rows = self._query_events(
            tenant_id=tenant_id,
            start_ts=None,
            end_ts=None,
            event_type=None,
        )
        weights = {
            "content_published": 1.0,
            "community_response_posted": 2.0,
            "partner_impression": 1.0,
            "partner_conversion": 5.0,
            "message_sent": 0.2,
        }

        scores: dict[str, float] = {}
        for row in rows:
            props = row["properties"]
            content_id = str(props.get("content_piece_id") or "").strip()
            if not content_id:
                continue
            explicit = props.get("engagement")
            if explicit is None:
                explicit = props.get("engagement_score")
            if explicit is None:
                explicit = weights.get(row["event_type"], 0.0)
            score = float(explicit or 0.0)
            scores[content_id] = scores.get(content_id, 0.0) + score

        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        bounded = max(1, min(int(limit), 100))
        return [name for name, _score in ordered[:bounded]]

    def total_sessions(self, tenant_id: str, start: Any, end: Any) -> int:
        start_ts, end_ts = self._coerce_window(start, end)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT session_id) AS count
                FROM analytics_events
                WHERE tenant_id = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
                  AND session_id IS NOT NULL
                  AND session_id != ''
                  AND event_type = 'session_started'
                """,
                (str(tenant_id), start_ts, end_ts),
            ).fetchone()
        return int(row["count"]) if row else 0

    def top_agents(
        self, tenant_id: str, start: Any, end: Any, limit: int = 5
    ) -> list[dict[str, Any]]:
        start_ts, end_ts = self._coerce_window(start, end)
        rows = self._query_events(
            tenant_id=tenant_id,
            start_ts=start_ts,
            end_ts=end_ts,
            event_type="agent_recruited",
        )

        counts: dict[str, int] = {}
        for row in rows:
            props = row["properties"]
            agent_name = str(props.get("agent") or props.get("agent_name") or "unknown").strip()
            if not agent_name:
                agent_name = "unknown"
            counts[agent_name] = counts.get(agent_name, 0) + 1

        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [
            {"agent": name, "count": count}
            for name, count in ordered[: max(1, min(int(limit), 20))]
        ]

    def agent_leaderboard(
        self,
        start: Any,
        end: Any,
        *,
        limit: int = 10,
        tenant_id: str | None = None,
        viewer_tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Rank agent performance with anonymized cross-tenant benchmarking.

        Example:
            >>> aggregator.agent_leaderboard(0, 1, limit=5)
            []
        """

        start_ts, end_ts = self._coerce_window(start, end)
        scoped_rows = self._query_events(
            tenant_id=tenant_id,
            start_ts=start_ts,
            end_ts=end_ts,
            event_type="agent_recruited",
        )
        if not scoped_rows:
            return []

        peer_rows = self._query_events(
            tenant_id=None,
            start_ts=start_ts,
            end_ts=end_ts,
            event_type="agent_recruited",
        )
        scoped_stats = _aggregate_agent_rows(scoped_rows)
        peer_stats = _aggregate_agent_rows(peer_rows)
        peer_average_by_agent: dict[str, list[float]] = {}
        for (_tenant, agent), stats in peer_stats.items():
            peer_average_by_agent.setdefault(agent, [])
        for (_tenant, agent), stats in peer_stats.items():
            peer_average_by_agent[agent].append(float(stats["score"]))
        benchmark_score = {
            agent: round(sum(scores) / float(len(scores)), 4) if scores else 0.0
            for agent, scores in peer_average_by_agent.items()
        }

        rows: list[dict[str, Any]] = []
        for (row_tenant_id, agent), stats in scoped_stats.items():
            alias = (
                "self"
                if viewer_tenant_id and row_tenant_id == viewer_tenant_id
                else _anonymize_tenant(row_tenant_id)
            )
            peer_score = benchmark_score.get(agent, float(stats["score"]))
            rows.append(
                {
                    "tenant": alias,
                    "agent": agent,
                    "mode": str(stats["mode"]),
                    "score": round(float(stats["score"]), 4),
                    "avg_confidence": round(float(stats["avg_confidence"]), 2),
                    "avg_cost_usd": round(float(stats["avg_cost_usd"]), 6),
                    "sample_size": int(stats["sample_size"]),
                    "federation_share": round(float(stats["federation_share"]), 4),
                    "benchmark_delta": round(float(stats["score"]) - float(peer_score), 4),
                    "is_self": bool(viewer_tenant_id and row_tenant_id == viewer_tenant_id),
                }
            )

        rows.sort(
            key=lambda item: (
                -float(item["score"]),
                -float(item["avg_confidence"]),
                str(item["agent"]),
                str(item["tenant"]),
            )
        )
        return rows[: max(1, min(int(limit), 100))]

    def raw_events(
        self,
        tenant_id: str,
        *,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 1000))
        rows = self._query_events(
            tenant_id=tenant_id,
            start_ts=None,
            end_ts=None,
            event_type=event_type,
            limit=bounded,
        )
        return rows[:bounded]

    def timeseries(self, tenant_id: str, metric: str, days: int = 30) -> list[dict[str, Any]]:
        bounded_days = max(1, min(int(days), 365))
        end_day = datetime.now(tz=timezone.utc).date()
        start_day = end_day.fromordinal(end_day.toordinal() - bounded_days + 1)

        points: list[dict[str, Any]] = []
        for offset in range(bounded_days):
            day = start_day.fromordinal(start_day.toordinal() + offset)
            day_label = day.isoformat()
            day_start = _day_start_ts(day)
            day_end = day_start + 86400.0
            if metric == "total_cost_usd":
                value = sum(self.cost_by_provider(tenant_id, day_start, day_end).values())
            elif metric == "approval_rate":
                value = self.approval_rate(tenant_id, day_start, day_end)
            elif metric == "daily_active_sessions":
                value = float(self.daily_active_sessions(tenant_id, day))
            else:
                # fallback metric: event volume for the day
                value = float(
                    len(self._query_events(tenant_id=tenant_id, start_ts=day_start, end_ts=day_end))
                )
            points.append({"date": day_label, "value": value})
        return points

    def _query_events(
        self,
        *,
        tenant_id: str | None,
        start_ts: float | None,
        end_ts: float | None,
        event_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT event_id, tenant_id, event_type, properties_json, timestamp, session_id "
            "FROM analytics_events WHERE 1=1"
        )
        params: list[Any] = []

        if tenant_id is not None:
            tenant = str(tenant_id).strip()
            if not tenant:
                return []
            query += " AND tenant_id = ?"
            params.append(tenant)

        if event_type:
            query += " AND event_type = ?"
            params.append(str(event_type).strip().lower())
        if start_ts is not None:
            query += " AND timestamp >= ?"
            params.append(float(start_ts))
        if end_ts is not None:
            query += " AND timestamp <= ?"
            params.append(float(end_ts))

        query += " ORDER BY timestamp ASC, event_id ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(max(1, min(int(limit), 5000)))

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, tuple(params)).fetchall()

        output: list[dict[str, Any]] = []
        for row in rows:
            output.append(
                {
                    "event_id": str(row["event_id"]),
                    "tenant_id": str(row["tenant_id"]),
                    "event_type": str(row["event_type"]),
                    "properties": _safe_json_dict(str(row["properties_json"])),
                    "timestamp": float(row["timestamp"]),
                    "session_id": str(row["session_id"] or ""),
                }
            )
        return output

    def _coerce_window(self, start: Any, end: Any) -> tuple[float, float]:
        start_ts = _to_timestamp(start)
        end_ts = _to_timestamp(end)
        if end_ts < start_ts:
            raise ValueError("end must be >= start")
        return start_ts, end_ts

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn


def _safe_json_dict(payload: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_date(value: str | date_cls | datetime) -> date_cls:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    if isinstance(value, date_cls):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError("date is required")
    return datetime.fromisoformat(text).date()


def _day_start_ts(day: date_cls) -> float:
    return datetime.combine(day, time_cls.min, tzinfo=timezone.utc).timestamp()


def _to_timestamp(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    if isinstance(value, date_cls):
        return _day_start_ts(value)
    text = str(value).strip()
    if not text:
        return time.time()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _aggregate_agent_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        props = row["properties"]
        agent = str(props.get("agent") or props.get("agent_name") or "unknown").strip() or "unknown"
        tenant_id = str(row["tenant_id"]).strip()
        if not tenant_id:
            continue
        key = (tenant_id, agent)
        bucket = grouped.setdefault(
            key,
            {
                "sample_size": 0,
                "total_confidence": 0.0,
                "total_cost_usd": 0.0,
                "federated": 0,
                "mode_counts": {},
            },
        )
        confidence = float(props.get("confidence", 0.0) or 0.0)
        cost_usd = float(props.get("cost_usd", 0.0) or 0.0)
        mode = str(props.get("mode") or "unknown").strip().lower() or "unknown"
        bucket["sample_size"] += 1
        bucket["total_confidence"] += confidence
        bucket["total_cost_usd"] += cost_usd
        bucket["federated"] += 1 if bool(props.get("federated")) else 0
        mode_counts = bucket["mode_counts"]
        mode_counts[mode] = int(mode_counts.get(mode, 0)) + 1

    for bucket in grouped.values():
        count = max(1, int(bucket["sample_size"]))
        avg_confidence = bucket["total_confidence"] / float(count)
        avg_cost = bucket["total_cost_usd"] / float(count)
        federation_share = bucket["federated"] / float(count)
        bucket["avg_confidence"] = avg_confidence
        bucket["avg_cost_usd"] = avg_cost
        bucket["federation_share"] = federation_share
        bucket["mode"] = _dominant_mode(bucket["mode_counts"])
        bucket["score"] = _performance_score(
            avg_confidence=avg_confidence,
            avg_cost_usd=avg_cost,
            federation_share=federation_share,
        )
    return grouped


def _dominant_mode(counts: dict[str, int]) -> str:
    if not counts:
        return "unknown"
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ordered[0][0]


def _performance_score(
    *, avg_confidence: float, avg_cost_usd: float, federation_share: float
) -> float:
    quality_component = max(0.0, min(1.0, avg_confidence / 100.0)) * 0.75
    cost_component = (1.0 / (1.0 + max(0.0, avg_cost_usd * 20.0))) * 0.20
    federation_component = max(0.0, min(1.0, federation_share)) * 0.05
    return round((quality_component + cost_component + federation_component) * 100.0, 4)


def _anonymize_tenant(tenant_id: str) -> str:
    digest = hashlib.sha256(str(tenant_id).encode("utf-8")).hexdigest()[:8]
    return f"tenant-{digest}"
