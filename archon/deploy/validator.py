"""Validation helpers for compose and Helm deployment assets."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


def validate_compose(path: str | Path = "deploy/docker-compose.yml") -> dict[str, Any]:
    """Validate the docker compose bundle used for on-prem installs.

    Example:
        >>> report = validate_compose("deploy/docker-compose.yml")
        >>> isinstance(report["ok"], bool)
        True
    """

    compose_path = Path(path)
    payload = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = payload.get("services", {}) if isinstance(payload, dict) else {}
    required = {"archon-api", "archon-worker", "otel-collector"}
    missing = sorted(required - set(services))
    findings = []
    if missing:
        findings.append(f"Missing required compose services: {', '.join(missing)}")
    if "postgres" not in services:
        findings.append(
            "Compose bundle is missing optional postgres service for enterprise installs."
        )
    return {
        "ok": not missing,
        "path": str(compose_path),
        "services": sorted(services),
        "findings": findings,
    }


def validate_observability_compose(
    path: str | Path = "docker-compose.observability.yml",
) -> dict[str, Any]:
    """Validate the standalone observability compose bundle.

    Example:
        >>> report = validate_observability_compose("docker-compose.observability.yml")
        >>> "services" in report
        True
    """

    compose_path = Path(path)
    payload = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = payload.get("services", {}) if isinstance(payload, dict) else {}
    required = {"prometheus", "grafana", "otel-collector"}
    missing = sorted(required - set(services))
    findings: list[str] = []
    if missing:
        findings.append(f"Observability compose is missing required services: {', '.join(missing)}")
    prometheus = services.get("prometheus", {}) if isinstance(services, dict) else {}
    extra_hosts = prometheus.get("extra_hosts", []) if isinstance(prometheus, dict) else []
    if "host.docker.internal:host-gateway" not in list(extra_hosts):
        findings.append("Prometheus service is missing host.docker.internal host-gateway mapping.")
    collector = services.get("otel-collector", {}) if isinstance(services, dict) else {}
    collector_volumes = collector.get("volumes", []) if isinstance(collector, dict) else []
    if "./deploy/otel-collector-config.yaml:/etc/otelcol-contrib/config.yaml:ro" not in list(
        collector_volumes
    ):
        findings.append(
            "otel-collector service must mount ./deploy/otel-collector-config.yaml read-only."
        )
    return {
        "ok": not findings,
        "path": str(compose_path),
        "services": sorted(services),
        "findings": findings,
    }


def validate_otel_collector_config(
    path: str | Path = "deploy/otel-collector-config.yaml",
) -> dict[str, Any]:
    """Validate the OTEL collector pipeline configuration.

    Example:
        >>> report = validate_otel_collector_config("deploy/otel-collector-config.yaml")
        >>> report["ok"] in {True, False}
        True
    """

    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "path": str(config_path),
            "pipelines": [],
            "findings": ["Collector config must parse to a mapping."],
        }

    receivers = payload.get("receivers", {}) if isinstance(payload.get("receivers"), dict) else {}
    processors = (
        payload.get("processors", {}) if isinstance(payload.get("processors"), dict) else {}
    )
    exporters = payload.get("exporters", {}) if isinstance(payload.get("exporters"), dict) else {}
    extensions = (
        payload.get("extensions", {}) if isinstance(payload.get("extensions"), dict) else {}
    )
    service = payload.get("service", {}) if isinstance(payload.get("service"), dict) else {}
    pipelines = service.get("pipelines", {}) if isinstance(service.get("pipelines"), dict) else {}
    findings: list[str] = []

    if "health_check" not in extensions:
        findings.append("Collector config should define the health_check extension.")
    if "otlp" not in receivers:
        findings.append("Collector config is missing the otlp receiver.")
    else:
        protocols = receivers.get("otlp", {}).get("protocols", {})
        if not isinstance(protocols, dict) or not {"grpc", "http"} <= set(protocols):
            findings.append("otlp receiver must enable both grpc and http protocols.")

    for pipeline_name in ("traces", "metrics", "logs"):
        pipeline = pipelines.get(pipeline_name)
        if not isinstance(pipeline, dict):
            findings.append(f"Collector config is missing the {pipeline_name} pipeline.")
            continue
        for key, registry in (
            ("receivers", receivers),
            ("processors", processors),
            ("exporters", exporters),
        ):
            refs = pipeline.get(key, [])
            if not isinstance(refs, list) or not refs:
                findings.append(f"{pipeline_name} pipeline must declare at least one {key[:-1]}.")
                continue
            unknown = [name for name in refs if name not in registry]
            if unknown:
                findings.append(
                    f"{pipeline_name} pipeline references undefined {key[:-1]}s: {', '.join(unknown)}"
                )

    return {
        "ok": not findings,
        "path": str(config_path),
        "pipelines": sorted(pipelines),
        "findings": findings,
    }


def validate_helm_chart(chart_dir: str | Path = "deploy/helm/archon") -> dict[str, Any]:
    """Validate the Helm chart structure and render templates with default values.

    Example:
        >>> report = validate_helm_chart("deploy/helm/archon")
        >>> "rendered_templates" in report
        True
    """

    chart_path = Path(chart_dir)
    chart = yaml.safe_load((chart_path / "Chart.yaml").read_text(encoding="utf-8"))
    values = yaml.safe_load((chart_path / "values.yaml").read_text(encoding="utf-8"))
    templates_dir = chart_path / "templates"
    rendered: dict[str, list[dict[str, Any]]] = {}
    findings: list[str] = []
    for template in sorted(templates_dir.glob("*.yaml")):
        docs = _render_template_docs(template, chart=chart, values=values)
        if not docs:
            findings.append(f"Template '{template.name}' did not render any YAML documents.")
        rendered[template.name] = docs
    return {
        "ok": not findings,
        "chart": chart.get("name", ""),
        "version": chart.get("version", ""),
        "rendered_templates": sorted(rendered),
        "findings": findings,
    }


def validate_all(root: str | Path = ".") -> dict[str, Any]:
    """Validate both compose and Helm assets from one repo root.

    Example:
        >>> report = validate_all(".")
        >>> set(report)
        {'ok', 'compose', 'observability', 'otel', 'helm'}
    """

    base = Path(root)
    compose = validate_compose(base / "deploy" / "docker-compose.yml")
    observability = validate_observability_compose(base / "docker-compose.observability.yml")
    otel = validate_otel_collector_config(base / "deploy" / "otel-collector-config.yaml")
    helm = validate_helm_chart(base / "deploy" / "helm" / "archon")
    return {
        "ok": bool(compose["ok"] and observability["ok"] and otel["ok"] and helm["ok"]),
        "compose": compose,
        "observability": observability,
        "otel": otel,
        "helm": helm,
    }


def _render_template_docs(
    template_path: Path,
    *,
    chart: dict[str, Any],
    values: dict[str, Any],
) -> list[dict[str, Any]]:
    rendered = _render_template(
        template_path.read_text(encoding="utf-8"), chart=chart, values=values
    )
    docs = [doc for doc in yaml.safe_load_all(rendered) if isinstance(doc, dict)]
    return docs


def _render_template(raw: str, *, chart: dict[str, Any], values: dict[str, Any]) -> str:
    result = raw.replace("{{ .Chart.Name }}", str(chart.get("name", "")))
    result = result.replace("{{ .Chart.AppVersion }}", str(chart.get("appVersion", "")))

    def replacer(match: re.Match[str]) -> str:
        dotted = match.group(1)
        value: Any = values
        for part in dotted.split("."):
            if not isinstance(value, dict):
                raise ValueError(f"Value path '.Values.{dotted}' is not resolvable.")
            value = value[part]
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    return re.sub(r"{{\s*\.Values\.([a-zA-Z0-9_.]+)\s*}}", replacer, result)
