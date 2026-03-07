"""Tests for on-prem compose, Helm, and deployment validation helpers."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path

import pytest
import yaml

from archon.onprem import (
    DeploymentConfig,
    DeployValidator,
    DockerComposeGenerator,
    HelmChartGenerator,
)


def _config(**overrides) -> DeploymentConfig:
    payload = {
        "tenant_id": "tenant-a",
        "tier": "enterprise",
        "enable_gpu": False,
        "ollama_models": [],
        "external_db_url": "",
        "smtp_host": "smtp.archon.local",
        "redis_url": "",
        "domain": "",
        "tls": False,
        "replicas": 3,
    }
    payload.update(overrides)
    return DeploymentConfig(**payload)


def _tmp_dir(name: str) -> Path:
    root = Path("archon/tests/_tmp_onprem")
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{name}-{uuid.uuid4().hex[:8]}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def test_docker_compose_generator_conditional_services_and_no_latest_tags() -> None:
    manifest = DockerComposeGenerator().generate(
        _config(enable_gpu=True, ollama_models=["llava:34b"], domain="archon.example", tls=True)
    )

    assert "ollama" in manifest.services
    assert "nginx" in manifest.services
    assert manifest.services["ollama"]["deploy"]["resources"]["reservations"]["devices"][0][
        "capabilities"
    ] == ["gpu"]
    assert all(
        ":latest" not in str(service.get("image", "")) for service in manifest.services.values()
    )
    assert manifest.services["archon-api"]["env_file"] == [".env.archon"]


def test_docker_compose_generator_omits_ollama_when_not_configured() -> None:
    manifest = DockerComposeGenerator().generate(_config())

    assert "ollama" not in manifest.services


def test_helm_chart_generator_writes_required_templates_and_values() -> None:
    output_dir = _tmp_dir("chart")
    chart = HelmChartGenerator().generate(
        _config(domain="archon.example", tls=True, replicas=4),
        output_dir,
    )
    values = yaml.safe_load(chart.values_yaml)
    hpa = yaml.safe_load(chart.templates["hpa.yaml"])
    pdb = yaml.safe_load(chart.templates["pdb.yaml"])
    ingress = yaml.safe_load(chart.templates["ingress.yaml"])

    assert sorted(chart.templates) == [
        "configmap.yaml",
        "deployment.yaml",
        "hpa.yaml",
        "ingress.yaml",
        "pdb.yaml",
        "secret.yaml",
        "service.yaml",
    ]
    assert values["replicas"] == 4
    assert hpa["spec"]["maxReplicas"] == 4
    assert pdb["spec"]["minAvailable"] == 1
    assert (
        ingress["metadata"]["annotations"]["cert-manager.io/cluster-issuer"] == "letsencrypt-prod"
    )


class _HttpClient:
    def __init__(
        self, *, health_status: int = 200, db_status: str = "ok", token_status: int = 200
    ) -> None:
        self.health_status = health_status
        self.db_status = db_status
        self.token_status = token_status

    def get(self, url: str):  # type: ignore[no-untyped-def]
        if url.endswith("/api/tags"):
            return _Response(200, {"models": []})
        return _Response(self.health_status, {"status": "ok", "db_status": self.db_status})

    def post(self, url: str, json: dict[str, object]):  # type: ignore[no-untyped-def]
        del json
        assert url.endswith("/webchat/token")
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbm9uOnNlc3Npb24iLCJzZXNzaW9uX2lkIjoicy0xIiwidGllciI6ImZyZWUiLCJpc3MiOiJhcmNob24td2ViY2hhdCIsImlhdCI6MTcxMDAwMDAwMCwiZXhwIjo0NzEwMDAwMDAwfQ.M_2QKCB4tf-bv6tR0s45u95MIZ0QHbJ3j3TCX7ubNqo"
        return _Response(self.token_status, {"token": token})


class _Response:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


def test_deploy_validator_api_reachable_and_blocking_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("archon.onprem.validator.verify_webchat_token", lambda token: {"ok": True})
    monkeypatch.setattr(
        "archon.onprem.validator._ssl_certificate_expiry",
        lambda base_url: datetime.now(timezone.utc) + timedelta(days=90),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout="ok", stderr=""
        ),  # type: ignore[index]
    )
    validator = DeployValidator(http_client=_HttpClient())

    report = validator.run_all(
        _config(tls=True, ollama_models=["llava:34b"]), "https://archon.example"
    )

    assert any(check.name == "api_reachable" and check.passed for check in report.checks)
    assert report.failed_count == 0
    assert report.blocking_failures == []


def test_deploy_validator_connection_error_and_ssl_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenClient:
        def get(self, url: str):  # type: ignore[no-untyped-def]
            raise RuntimeError("connection refused")

        def post(self, url: str, json: dict[str, object]):  # type: ignore[no-untyped-def]
            raise RuntimeError("connection refused")

    monkeypatch.setattr(
        "archon.onprem.validator._ssl_certificate_expiry",
        lambda base_url: datetime.now(timezone.utc) + timedelta(days=5),
    )
    monkeypatch.setattr("archon.onprem.validator.verify_webchat_token", lambda token: {"ok": True})
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=1, stdout="", stderr="bad"
        ),  # type: ignore[index]
    )
    validator = DeployValidator(http_client=_BrokenClient())  # type: ignore[arg-type]

    report = validator.run_all(_config(tls=True), "https://archon.example")

    assert any(check.name == "api_reachable" and not check.passed for check in report.checks)
    assert any(check.name == "ssl_valid" and not check.passed for check in report.checks)
    assert all(check.severity == "critical" for check in report.blocking_failures)


@pytest.mark.parametrize(
    ("enable_gpu", "with_ollama", "with_domain", "tls"),
    list(product((False, True), repeat=4)),
)
def test_docker_compose_generator_configuration_matrix(
    enable_gpu: bool,
    with_ollama: bool,
    with_domain: bool,
    tls: bool,
) -> None:
    config = _config(
        enable_gpu=enable_gpu,
        ollama_models=["llava:34b"] if with_ollama else [],
        domain="archon.example" if with_domain else "",
        tls=tls,
    )
    manifest = DockerComposeGenerator().generate(config)

    assert ("ollama" in manifest.services) is with_ollama
    assert ("nginx" in manifest.services) is with_domain
    if with_ollama and enable_gpu:
        assert "deploy" in manifest.services["ollama"]
    else:
        assert "ollama" not in manifest.services or "deploy" not in manifest.services["ollama"]
    if with_domain and tls:
        assert manifest.services["nginx"]["environment"]["ARCHON_TLS"] == "true"


@pytest.mark.parametrize("replicas", range(1, 11))
def test_helm_chart_generator_replica_matrix(replicas: int) -> None:
    chart = HelmChartGenerator().generate(_config(replicas=replicas), _tmp_dir(f"chart-{replicas}"))
    hpa = yaml.safe_load(chart.templates["hpa.yaml"])

    assert hpa["spec"]["minReplicas"] == 1
    assert hpa["spec"]["maxReplicas"] == replicas
