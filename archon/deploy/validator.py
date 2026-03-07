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
        {'ok', 'compose', 'helm'}
    """

    base = Path(root)
    compose = validate_compose(base / "deploy" / "docker-compose.yml")
    helm = validate_helm_chart(base / "deploy" / "helm" / "archon")
    return {"ok": bool(compose["ok"] and helm["ok"]), "compose": compose, "helm": helm}


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
