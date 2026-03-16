"""Prometheus-style metrics helpers with graceful local fallbacks."""

from __future__ import annotations

import importlib.util
import sqlite3
from collections import defaultdict
from threading import Lock
from typing import Any

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

_COUNTER_DEFS = {
    "archon_requests_total": ("Total ARCHON HTTP requests.", ("method", "path", "status")),
    "archon_llm_calls_total": ("Total LLM provider calls.", ("provider", "model")),
    "archon_tokens_total": ("Total LLM tokens processed.", ("provider", "direction")),
    "archon_approvals_total": ("Approval outcomes.", ("action", "outcome")),
    "archon_agents_recruited_total": ("Agent recruitment count.", ("agent_name",)),
    "archon_emails_sent_total": ("Outbound email attempts.", ("backend", "status")),
    "archon_worker_tasks_total": ("Background worker task outcomes.", ("mode", "status")),
}

_GAUGE_DEFS = {
    "archon_active_sessions": ("Active session count.", ()),
    "archon_pending_approvals": ("Pending approval count.", ()),
    "archon_budget_used_ratio": ("Budget used ratio per tenant.", ("tenant_id",)),
}

_HISTOGRAM_DEFS = {
    "archon_request_duration_seconds": (
        "ARCHON HTTP request duration.",
        ("path",),
        (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    ),
    "archon_llm_latency_seconds": (
        "LLM call latency.",
        ("provider", "model"),
        (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    ),
    "archon_approval_wait_seconds": (
        "Approval wait duration.",
        ("action",),
        (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
    ),
    "archon_worker_task_duration_seconds": (
        "Background worker task duration.",
        ("mode",),
        (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    ),
}


def _label_key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_labels(label_pairs: tuple[tuple[str, str], ...]) -> str:
    if not label_pairs:
        return ""
    escaped = ",".join(f'{key}="{_escape_label(value)}"' for key, value in label_pairs)
    return f"{{{escaped}}}"


class Metrics:
    """Singleton metrics registry with optional Prometheus integration."""

    _instance: "Metrics | None" = None
    _force_noop: bool | None = None

    def __init__(self) -> None:
        self._lock = Lock()
        self._prometheus_enabled = bool(
            _module_available("prometheus_client") and self._force_noop is not True
        )
        self._counter_values: dict[str, dict[tuple[tuple[str, str], ...], float]] = {
            name: defaultdict(float) for name in _COUNTER_DEFS
        }
        self._gauge_values: dict[str, dict[tuple[tuple[str, str], ...], float]] = {
            name: defaultdict(float) for name in _GAUGE_DEFS
        }
        self._histogram_values: dict[str, dict[tuple[tuple[str, str], ...], dict[str, Any]]] = {
            name: defaultdict(dict) for name in _HISTOGRAM_DEFS
        }
        self._prometheus_registry = None
        self._prometheus_counters: dict[str, Any] = {}
        self._prometheus_gauges: dict[str, Any] = {}
        self._prometheus_histograms: dict[str, Any] = {}
        self._prometheus_generate_latest = None
        self._prometheus_content_type = PROMETHEUS_CONTENT_TYPE
        if self._prometheus_enabled:
            self._init_prometheus()

    @classmethod
    def get_instance(cls) -> "Metrics":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_for_tests(cls, *, force_noop: bool | None = None) -> None:
        cls._force_noop = force_noop
        cls._instance = None

    @property
    def content_type(self) -> str:
        return self._prometheus_content_type

    def increment_request(self, *, method: str, path: str, status: int) -> None:
        self._inc_counter(
            "archon_requests_total",
            {"method": method.upper(), "path": path, "status": str(int(status))},
            amount=1.0,
        )

    def observe_request_duration(self, *, path: str, duration_seconds: float) -> None:
        self._observe_histogram(
            "archon_request_duration_seconds",
            {"path": path},
            float(duration_seconds),
        )

    def record_llm_call(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_seconds: float,
    ) -> None:
        labels = {"provider": provider or "unknown", "model": model or "unknown"}
        self._inc_counter("archon_llm_calls_total", labels, amount=1.0)
        self._inc_counter(
            "archon_tokens_total",
            {"provider": labels["provider"], "direction": "input"},
            amount=max(0.0, float(input_tokens)),
        )
        self._inc_counter(
            "archon_tokens_total",
            {"provider": labels["provider"], "direction": "output"},
            amount=max(0.0, float(output_tokens)),
        )
        self._observe_histogram("archon_llm_latency_seconds", labels, float(latency_seconds))

    def record_approval(self, *, action: str, outcome: str, wait_seconds: float) -> None:
        normalized_action = action or "unknown"
        normalized_outcome = outcome or "unknown"
        self._inc_counter(
            "archon_approvals_total",
            {"action": normalized_action, "outcome": normalized_outcome},
            amount=1.0,
        )
        self._observe_histogram(
            "archon_approval_wait_seconds",
            {"action": normalized_action},
            float(wait_seconds),
        )

    def increment_agents_recruited(self, agent_name: str) -> None:
        self._inc_counter(
            "archon_agents_recruited_total",
            {"agent_name": agent_name or "unknown"},
            amount=1.0,
        )

    def increment_email_sent(self, *, backend: str, status: str) -> None:
        self._inc_counter(
            "archon_emails_sent_total",
            {"backend": backend or "unknown", "status": status or "unknown"},
            amount=1.0,
        )

    def record_worker_task(self, *, mode: str, status: str, duration_seconds: float) -> None:
        """Record one background worker task outcome.

        Example:
            >>> metrics = Metrics.get_instance()
            >>> metrics.record_worker_task(mode="debate", status="completed", duration_seconds=0.1)
        """

        normalized_mode = mode or "unknown"
        normalized_status = status or "unknown"
        self._inc_counter(
            "archon_worker_tasks_total",
            {"mode": normalized_mode, "status": normalized_status},
            amount=1.0,
        )
        self._observe_histogram(
            "archon_worker_task_duration_seconds",
            {"mode": normalized_mode},
            float(duration_seconds),
        )

    def set_active_sessions(self, value: int | float) -> None:
        self._set_gauge("archon_active_sessions", {}, float(value))

    def set_pending_approvals(self, value: int | float) -> None:
        self._set_gauge("archon_pending_approvals", {}, float(value))

    def set_budget_used_ratio(self, *, tenant_id: str, ratio: float) -> None:
        bounded = min(1.0, max(0.0, float(ratio)))
        self._set_gauge("archon_budget_used_ratio", {"tenant_id": tenant_id or "unknown"}, bounded)

    def record_task_budget(self, *, tenant_id: str, spent_usd: float, budget_usd: float) -> None:
        if float(budget_usd) <= 0:
            return
        self.set_budget_used_ratio(tenant_id=tenant_id, ratio=float(spent_usd) / float(budget_usd))

    def refresh_runtime_gauges(self, app: Any) -> None:
        orchestrator = getattr(getattr(app, "state", None), "orchestrator", None)
        if orchestrator is not None and hasattr(orchestrator, "approval_gate"):
            pending = getattr(orchestrator.approval_gate, "pending_actions", ())
            self.set_pending_approvals(len(tuple(pending)))
        self.set_active_sessions(0)

    def render_prometheus_text(self) -> str:
        if self._prometheus_enabled and self._prometheus_registry is not None:
            payload = self._prometheus_generate_latest(self._prometheus_registry)
            return payload.decode("utf-8")

        lines: list[str] = []
        for name, (help_text, _label_names) in _COUNTER_DEFS.items():
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} counter")
            for labels, value in sorted(self._counter_values[name].items()):
                lines.append(f"{name}{_format_labels(labels)} {value}")
        for name, (help_text, _label_names) in _GAUGE_DEFS.items():
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
            for labels, value in sorted(self._gauge_values[name].items()):
                lines.append(f"{name}{_format_labels(labels)} {value}")
        for name, (help_text, _label_names, buckets) in _HISTOGRAM_DEFS.items():
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} histogram")
            for labels, value in sorted(self._histogram_values[name].items()):
                counts = value.get("bucket_counts", {})
                for bucket in buckets:
                    bucket_labels = labels + (("le", str(bucket)),)
                    lines.append(
                        f"{name}_bucket{_format_labels(bucket_labels)} {counts.get(bucket, 0)}"
                    )
                inf_labels = labels + (("le", "+Inf"),)
                lines.append(f"{name}_bucket{_format_labels(inf_labels)} {value.get('count', 0)}")
                lines.append(f"{name}_sum{_format_labels(labels)} {value.get('sum', 0.0)}")
                lines.append(f"{name}_count{_format_labels(labels)} {value.get('count', 0)}")
        return "\n".join(lines) + "\n"

    def _init_prometheus(self) -> None:
        try:
            from prometheus_client import (
                CollectorRegistry,
                Counter,
                Gauge,
                Histogram,
                generate_latest,
            )
        except Exception:
            self._prometheus_enabled = False
            return

        self._prometheus_registry = CollectorRegistry()
        self._prometheus_generate_latest = generate_latest
        for name, (help_text, label_names) in _COUNTER_DEFS.items():
            self._prometheus_counters[name] = Counter(
                name,
                help_text,
                labelnames=label_names,
                registry=self._prometheus_registry,
            )
        for name, (help_text, label_names) in _GAUGE_DEFS.items():
            self._prometheus_gauges[name] = Gauge(
                name,
                help_text,
                labelnames=label_names,
                registry=self._prometheus_registry,
            )
        for name, (help_text, label_names, buckets) in _HISTOGRAM_DEFS.items():
            self._prometheus_histograms[name] = Histogram(
                name,
                help_text,
                labelnames=label_names,
                buckets=buckets,
                registry=self._prometheus_registry,
            )

    def _inc_counter(self, name: str, labels: dict[str, str], *, amount: float) -> None:
        key = _label_key(labels)
        with self._lock:
            self._counter_values[name][key] += float(amount)
        counter = self._prometheus_counters.get(name)
        if counter is not None:
            counter.labels(**labels).inc(float(amount))

    def _set_gauge(self, name: str, labels: dict[str, str], value: float) -> None:
        key = _label_key(labels)
        with self._lock:
            self._gauge_values[name][key] = float(value)
        gauge = self._prometheus_gauges.get(name)
        if gauge is not None:
            gauge.labels(**labels).set(float(value))

    def _observe_histogram(self, name: str, labels: dict[str, str], value: float) -> None:
        key = _label_key(labels)
        _, _, buckets = _HISTOGRAM_DEFS[name]
        with self._lock:
            bucket_counts = self._histogram_values[name][key].setdefault(
                "bucket_counts",
                {bucket: 0 for bucket in buckets},
            )
            for bucket in buckets:
                if value <= bucket:
                    bucket_counts[bucket] += 1
            self._histogram_values[name][key]["count"] = (
                int(self._histogram_values[name][key].get("count", 0)) + 1
            )
            self._histogram_values[name][key]["sum"] = float(
                self._histogram_values[name][key].get("sum", 0.0)
            ) + float(value)
        histogram = self._prometheus_histograms.get(name)
        if histogram is not None:
            histogram.labels(**labels).observe(float(value))


def _count_sessions(session_store: Any) -> int | None:
    if session_store is None:
        return None
    sessions = getattr(session_store, "_sessions", None)
    if isinstance(sessions, dict):
        return len(sessions)
    connect = getattr(session_store, "_connect", None)
    if callable(connect):
        try:
            with connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS total FROM sessions").fetchone()
            if row is None:
                return 0
            return int(row["total"] if hasattr(row, "__getitem__") else row[0])
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return None
    return None


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False
