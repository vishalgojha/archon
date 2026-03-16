"""Tracing helpers with optional OpenTelemetry integration."""

from __future__ import annotations

import contextvars
import importlib.util
import os
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Literal

from archon.core.approval_gate import ApprovalDeniedError, ApprovalTimeoutError

_span_stack: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "archon_span_stack", default=()
)
_run_stats: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "archon_run_stats", default=None
)


@dataclass(slots=True)
class RecordedSpan:
    """Serialized span shape exposed via the local trace endpoint."""

    span_id: str
    parent_id: str | None
    name: str
    service_name: str
    status: str
    started_at: float
    ended_at: float
    duration_ms: float
    attributes: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InMemorySpanExporter:
    """Bounded in-memory span collector for local development."""

    def __init__(self, *, max_spans: int = 1000) -> None:
        self._spans: deque[RecordedSpan] = deque(maxlen=max_spans)

    def export(self, span: RecordedSpan) -> None:
        self._spans.append(span)

    def list_spans(self, *, limit: int = 100, failed_only: bool = False) -> list[dict[str, Any]]:
        rows = list(self._spans)
        if failed_only:
            rows = [row for row in rows if row.status != "ok"]
        bounded = rows[-max(1, int(limit)) :]
        return [row.to_dict() for row in bounded]

    def clear(self) -> None:
        self._spans.clear()


class _SpanContextManager:
    def __init__(
        self,
        *,
        name: str,
        service_name: str,
        delegate_tracer: Any,
        exporter: InMemorySpanExporter,
    ) -> None:
        self._name = name
        self._service_name = service_name
        self._delegate_tracer = delegate_tracer
        self._exporter = exporter
        self._record = RecordedSpan(
            span_id=f"span-{uuid.uuid4().hex[:16]}",
            parent_id=None,
            name=name,
            service_name=service_name,
            status="ok",
            started_at=0.0,
            ended_at=0.0,
            duration_ms=0.0,
        )
        self._delegate_context = None
        self._delegate_span = None
        self._stack_token = None

    def __enter__(self) -> "_SpanContextManager":
        stack = _span_stack.get()
        self._record.parent_id = stack[-1] if stack else None
        self._record.started_at = time.time()
        self._stack_token = _span_stack.set(stack + (self._record.span_id,))
        if self._delegate_tracer is not None:
            try:
                self._delegate_context = self._delegate_tracer.start_as_current_span(self._name)
                self._delegate_span = self._delegate_context.__enter__()
            except Exception:
                self._delegate_context = None
                self._delegate_span = None
        return self

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
        if exc is not None:
            self._record.status = "error"
            self._record.error = str(exc)
            self.record_exception(exc)
        self._record.ended_at = time.time()
        self._record.duration_ms = round(
            max(0.0, self._record.ended_at - self._record.started_at) * 1000.0,
            3,
        )
        if self._stack_token is not None:
            _span_stack.reset(self._stack_token)
        if self._delegate_context is not None:
            self._delegate_context.__exit__(exc_type, exc, tb)
        self._exporter.export(self._record)
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        normalized = _normalize_attribute(value)
        self._record.attributes[str(key)] = normalized
        if self._delegate_span is not None:
            try:
                self._delegate_span.set_attribute(str(key), normalized)
            except Exception:
                return

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        for key, value in attributes.items():
            self.set_attribute(str(key), value)

    def record_exception(self, exc: Exception) -> None:
        if self._delegate_span is not None:
            try:
                self._delegate_span.record_exception(exc)
            except Exception:
                return


class _TracerAdapter:
    def __init__(
        self,
        *,
        name: str,
        service_name: str,
        delegate_tracer: Any,
        exporter: InMemorySpanExporter,
    ) -> None:
        self._name = name
        self._service_name = service_name
        self._delegate_tracer = delegate_tracer
        self._exporter = exporter

    def start_as_current_span(self, name: str) -> _SpanContextManager:
        return _SpanContextManager(
            name=name,
            service_name=self._service_name,
            delegate_tracer=self._delegate_tracer,
            exporter=self._exporter,
        )


class TracingSetup:
    """Global tracing facade for ARCHON."""

    _configured = False
    _service_name = "archon"
    _exporter = InMemorySpanExporter()
    _delegate_api = None
    _delegate_provider = None
    _tracers: dict[str, _TracerAdapter] = {}
    _force_noop: bool | None = None
    _fastapi_apps: set[int] = set()

    @classmethod
    def configure(
        cls, service_name: str = "archon", otlp_endpoint: str | None = None
    ) -> _TracerAdapter:
        if cls._configured:
            return cls.get_tracer(service_name)

        cls._service_name = str(service_name or "archon")
        endpoint = (
            str(otlp_endpoint or "").strip()
            or str(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")).strip()
        )
        cls._delegate_api = None
        cls._delegate_provider = None
        if cls._force_noop is not True and _module_available("opentelemetry.sdk"):
            try:
                from opentelemetry import trace as otel_trace
                from opentelemetry.sdk.resources import SERVICE_NAME, Resource
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

                provider = TracerProvider(
                    resource=Resource.create({SERVICE_NAME: cls._service_name})
                )
                exporter = None
                if endpoint and _module_available(
                    "opentelemetry.exporter.otlp.proto.http.trace_exporter"
                ):
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                        OTLPSpanExporter,
                    )

                    exporter = OTLPSpanExporter(endpoint=endpoint)
                if exporter is None:
                    exporter = ConsoleSpanExporter()
                provider.add_span_processor(SimpleSpanProcessor(exporter))
                try:
                    otel_trace.set_tracer_provider(provider)
                except Exception:
                    pass
                cls._delegate_api = otel_trace
                cls._delegate_provider = provider
            except Exception:
                cls._delegate_api = None
                cls._delegate_provider = None

        cls._configured = True
        return cls.get_tracer(cls._service_name)

    @classmethod
    def get_tracer(cls, name: str) -> _TracerAdapter:
        if not cls._configured:
            cls.configure()
        tracer_name = str(name or cls._service_name)
        cached = cls._tracers.get(tracer_name)
        if cached is not None:
            return cached
        delegate = (
            cls._delegate_api.get_tracer(tracer_name) if cls._delegate_api is not None else None
        )
        tracer = _TracerAdapter(
            name=tracer_name,
            service_name=cls._service_name,
            delegate_tracer=delegate,
            exporter=cls._exporter,
        )
        cls._tracers[tracer_name] = tracer
        return tracer

    @classmethod
    def list_spans(cls, *, limit: int = 100, failed_only: bool = False) -> list[dict[str, Any]]:
        return cls._exporter.list_spans(limit=limit, failed_only=failed_only)

    @classmethod
    def clear_spans(cls) -> None:
        cls._exporter.clear()

    @classmethod
    def reset_for_tests(cls, *, force_noop: bool | None = None) -> None:
        cls._configured = False
        cls._service_name = "archon"
        cls._exporter = InMemorySpanExporter()
        cls._delegate_api = None
        cls._delegate_provider = None
        cls._tracers = {}
        cls._force_noop = force_noop
        cls._fastapi_apps = set()

    @classmethod
    def instrument_fastapi(cls, app: Any) -> None:
        app_id = id(app)
        if app_id in cls._fastapi_apps:
            return
        cls._fastapi_apps.add(app_id)
        if cls._force_noop is True:
            return
        if not _module_available("opentelemetry.instrumentation.fastapi"):
            return
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
        except Exception:
            return

    @classmethod
    def instrument_orchestrator(cls, orchestrator: Any) -> None:
        if getattr(orchestrator, "_archon_tracing_instrumented", False):
            return
        setattr(orchestrator, "_archon_tracing_instrumented", True)
        tracer = cls.get_tracer("archon.orchestrator")
        cls._instrument_provider_router(getattr(orchestrator, "provider_router", None))
        cls._instrument_approval_gate(getattr(orchestrator, "approval_gate", None))
        cls._instrument_swarm_builders(getattr(orchestrator, "swarm_router", None))
        cls._instrument_agent(getattr(orchestrator, "cost_optimizer", None))

        original_execute = getattr(orchestrator, "execute")

        async def wrapped_execute(*args: Any, **kwargs: Any):
            from archon.observability.metrics import Metrics

            effective_context = dict(kwargs.get("context") or {})
            tenant_id = _tenant_from_context(effective_context)
            mode = str(kwargs.get("mode", "debate"))
            stats: dict[str, Any] = {
                "tenant_id": tenant_id,
                "mode": mode,
                "agent_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
            }
            token = _run_stats.set(stats)
            with tracer.start_as_current_span("orchestrator.run") as span:
                span.set_attribute("tenant_id", tenant_id)
                span.set_attribute("mode", mode)
                try:
                    result = await original_execute(*args, **kwargs)
                except Exception as exc:
                    span.set_attribute("agent_count", int(stats["agent_count"]))
                    span.set_attribute(
                        "token_count", int(stats["input_tokens"] + stats["output_tokens"])
                    )
                    span.set_attribute("cost_usd", round(float(stats["cost_usd"]), 6))
                    span.record_exception(exc)
                    raise
                finally:
                    _run_stats.reset(token)
                budget = getattr(result, "budget", {}) or {}
                cost_usd = float(budget.get("spent_usd", stats["cost_usd"]) or 0.0)
                token_count = int(stats["input_tokens"] + stats["output_tokens"])
                span.set_attribute("tenant_id", tenant_id)
                span.set_attribute("mode", getattr(result, "mode", mode))
                span.set_attribute("agent_count", int(stats["agent_count"]))
                span.set_attribute("token_count", token_count)
                span.set_attribute("cost_usd", round(cost_usd, 6))
                Metrics.get_instance().record_task_budget(
                    tenant_id=tenant_id,
                    spent_usd=cost_usd,
                    budget_usd=float(budget.get("budget_usd", 0.0) or 0.0),
                )
                return result

        setattr(orchestrator, "execute", wrapped_execute)

    @classmethod
    def _instrument_provider_router(cls, provider_router: Any) -> None:
        if provider_router is None or getattr(
            provider_router, "_archon_tracing_instrumented", False
        ):
            return
        setattr(provider_router, "_archon_tracing_instrumented", True)
        tracer = cls.get_tracer("archon.providers")

        for attr_name in ("invoke", "invoke_multimodal"):
            original = getattr(provider_router, attr_name)

            async def wrapped_call(
                *args: Any,
                __original=original,
                __attr_name=attr_name,
                **kwargs: Any,
            ):
                from archon.observability.metrics import Metrics

                started = time.perf_counter()
                role = str(kwargs.get("role") or "fast")
                selection = None
                try:
                    selection = provider_router.resolve_provider(
                        role=role,
                        model_override=kwargs.get("model_override"),
                        provider_override=kwargs.get("provider_override"),
                    )
                except Exception:
                    selection = None

                with tracer.start_as_current_span("llm.call") as span:
                    if selection is not None:
                        span.set_attribute("provider", selection.provider)
                        span.set_attribute("model", selection.model)
                    try:
                        response = await __original(*args, **kwargs)
                    except Exception as exc:
                        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
                        span.set_attribute("latency_ms", latency_ms)
                        span.record_exception(exc)
                        raise
                    usage = getattr(response, "usage", None)
                    provider = str(
                        getattr(response, "provider", "")
                        or getattr(selection, "provider", "unknown")
                    )
                    model = str(
                        getattr(response, "model", "") or getattr(selection, "model", "unknown")
                    )
                    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
                    span.set_attributes(
                        {
                            "provider": provider,
                            "model": model,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "latency_ms": latency_ms,
                        }
                    )
                    Metrics.get_instance().record_llm_call(
                        provider=provider,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        latency_seconds=latency_ms / 1000.0,
                    )
                    stats = _run_stats.get()
                    if isinstance(stats, dict):
                        stats["input_tokens"] = int(stats.get("input_tokens", 0)) + input_tokens
                        stats["output_tokens"] = int(stats.get("output_tokens", 0)) + output_tokens
                        stats["cost_usd"] = float(stats.get("cost_usd", 0.0)) + float(
                            getattr(usage, "cost_usd", 0.0) or 0.0
                        )
                    return response

            setattr(provider_router, attr_name, wrapped_call)

    @classmethod
    def _instrument_approval_gate(cls, approval_gate: Any) -> None:
        if approval_gate is None or getattr(approval_gate, "_archon_tracing_instrumented", False):
            return
        setattr(approval_gate, "_archon_tracing_instrumented", True)
        tracer = cls.get_tracer("archon.approvals")
        original_check = getattr(approval_gate, "check")

        async def wrapped_check(*args: Any, **kwargs: Any):
            from archon.observability.metrics import Metrics

            action = str(kwargs.get("action") or (args[0] if args else "unknown"))
            started = time.perf_counter()
            with tracer.start_as_current_span("approval.check") as span:
                span.set_attribute("action", action)
                try:
                    result = await original_check(*args, **kwargs)
                except ApprovalTimeoutError as exc:
                    wait_ms = round((time.perf_counter() - started) * 1000.0, 3)
                    span.set_attribute("approved", False)
                    span.set_attribute("wait_time_ms", wait_ms)
                    Metrics.get_instance().record_approval(
                        action=action,
                        outcome="timeout",
                        wait_seconds=wait_ms / 1000.0,
                    )
                    span.record_exception(exc)
                    raise
                except ApprovalDeniedError as exc:
                    wait_ms = round((time.perf_counter() - started) * 1000.0, 3)
                    span.set_attribute("approved", False)
                    span.set_attribute("wait_time_ms", wait_ms)
                    Metrics.get_instance().record_approval(
                        action=action,
                        outcome="denied",
                        wait_seconds=wait_ms / 1000.0,
                    )
                    span.record_exception(exc)
                    raise
                wait_ms = round((time.perf_counter() - started) * 1000.0, 3)
                span.set_attribute("approved", True)
                span.set_attribute("wait_time_ms", wait_ms)
                Metrics.get_instance().record_approval(
                    action=action,
                    outcome="approved",
                    wait_seconds=wait_ms / 1000.0,
                )
                return result

        setattr(approval_gate, "check", wrapped_check)

    @classmethod
    def _instrument_swarm_builders(cls, router: Any) -> None:
        if router is None or getattr(router, "_archon_tracing_builders", False):
            return
        setattr(router, "_archon_tracing_builders", True)
        for attr_name in ("build_debate_swarm",):
            if not hasattr(router, attr_name):
                continue
            original = getattr(router, attr_name)

            def wrapped_build(*args: Any, __original=original, **kwargs: Any):
                swarm = __original(*args, **kwargs)
                cls._instrument_swarm_agents(swarm)
                return swarm

            setattr(router, attr_name, wrapped_build)

    @classmethod
    def _instrument_swarm_agents(cls, swarm: Any) -> None:
        if not is_dataclass(swarm):
            return
        for current in fields(swarm):
            cls._instrument_agent(getattr(swarm, current.name, None))

    @classmethod
    def _instrument_agent(cls, agent: Any) -> None:
        if (
            agent is None
            or getattr(agent, "_archon_tracing_agent", False)
            or not hasattr(agent, "run")
        ):
            return
        setattr(agent, "_archon_tracing_agent", True)
        tracer = cls.get_tracer(f"archon.agent.{getattr(agent, 'name', 'unknown')}")
        original_run = getattr(agent, "run")

        async def wrapped_run(*args: Any, **kwargs: Any):
            from archon.observability.metrics import Metrics

            task_id = str(kwargs.get("task_id") or (args[2] if len(args) > 2 else ""))
            agent_name = str(getattr(agent, "name", type(agent).__name__))
            Metrics.get_instance().increment_agents_recruited(agent_name)
            stats = _run_stats.get()
            if isinstance(stats, dict):
                stats["agent_count"] = int(stats.get("agent_count", 0)) + 1
            with tracer.start_as_current_span("agent.run") as span:
                span.set_attribute("agent_name", agent_name)
                span.set_attribute("task_id", task_id)
                try:
                    result = await original_run(*args, **kwargs)
                except Exception as exc:
                    span.set_attribute("success", False)
                    span.record_exception(exc)
                    raise
                span.set_attribute("success", True)
                return result

        setattr(agent, "run", wrapped_run)

    @classmethod
    def _instrument_email_agent(cls, email_agent: Any) -> None:
        if (
            email_agent is None
            or getattr(email_agent, "_archon_email_metrics", False)
            or not hasattr(email_agent, "send_email")
        ):
            return
        setattr(email_agent, "_archon_email_metrics", True)
        original_send = getattr(email_agent, "send_email")

        async def wrapped_send(*args: Any, **kwargs: Any):
            from archon.observability.metrics import Metrics

            try:
                result = await original_send(*args, **kwargs)
            except Exception:
                Metrics.get_instance().increment_email_sent(backend="unknown", status="failed")
                raise
            metadata = getattr(result, "metadata", {}) or {}
            backend = str(metadata.get("provider", "unknown"))
            accepted = bool(metadata.get("accepted", False))
            Metrics.get_instance().increment_email_sent(
                backend=backend,
                status="sent" if accepted else "rejected",
            )
            return result

        setattr(email_agent, "send_email", wrapped_send)


def _normalize_attribute(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_normalize_attribute(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_attribute(item) for key, item in value.items()}
    return str(value)


def _tenant_from_context(context: dict[str, Any]) -> str:
    tenant_id = str(context.get("tenant_id", "")).strip()
    if tenant_id:
        return tenant_id
    nested = context.get("tenant_ctx")
    if isinstance(nested, dict):
        nested_tenant = str(nested.get("tenant_id", "")).strip()
        if nested_tenant:
            return nested_tenant
    return "anonymous"


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False
