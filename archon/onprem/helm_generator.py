"""Helm chart generator for ARCHON Kubernetes deployments."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import yaml

from archon.onprem.compose_generator import DeploymentConfig


@dataclass(slots=True)
class HelmChart:
    """Generated Helm chart payload.

    Example:
        >>> HelmChart(chart_yaml="name: archon", values_yaml="{}", templates={}).chart_yaml.startswith("apiVersion")
        False
    """

    chart_yaml: str
    values_yaml: str
    templates: dict[str, str]


class HelmChartGenerator:
    """Generate a Kubernetes Helm chart for one deployment config.

    Example:
        >>> generator = HelmChartGenerator()
        >>> chart = generator.generate(DeploymentConfig("tenant-a", "enterprise", False, [], "", "", "", "", False, 2), Path("archon/tests/_tmp_helm_example"))
        >>> "deployment.yaml" in chart.templates
        True
    """

    def generate(self, config: DeploymentConfig, output_dir: Path) -> HelmChart:
        """Write a Helm chart directory and return the generated artifacts.

        Example:
            >>> generator = HelmChartGenerator()
            >>> chart = generator.generate(DeploymentConfig("tenant-a", "enterprise", False, [], "", "", "", "", False, 2), Path("archon/tests/_tmp_helm_example_2"))
            >>> isinstance(chart.values_yaml, str)
            True
        """

        output_dir.mkdir(parents=True, exist_ok=True)
        templates_dir = output_dir / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)

        chart_payload = {
            "apiVersion": "v2",
            "name": "archon",
            "description": "ARCHON on-prem deployment",
            "type": "application",
            "version": "0.1.0",
            "appVersion": "0.1.0",
        }
        values_payload = {
            "tenantId": config.tenant_id,
            "tier": config.tier,
            "enableGpu": bool(config.enable_gpu),
            "ollamaModels": list(config.ollama_models),
            "externalDbUrl": config.external_db_url,
            "smtpHost": config.smtp_host,
            "redisUrl": config.redis_url,
            "domain": config.domain,
            "tls": bool(config.tls),
            "replicas": max(1, int(config.replicas)),
            "image": {"repository": "ghcr.io/archon/api", "tag": "0.1.0"},
        }
        chart_yaml = yaml.safe_dump(chart_payload, sort_keys=False)
        values_yaml = yaml.safe_dump(values_payload, sort_keys=False)

        templates = {
            "deployment.yaml": self._deployment_template(config),
            "service.yaml": self._service_template(config),
            "ingress.yaml": self._ingress_template(config),
            "configmap.yaml": self._configmap_template(config),
            "secret.yaml": self._secret_template(config),
            "hpa.yaml": self._hpa_template(config),
            "pdb.yaml": self._pdb_template(),
        }

        (output_dir / "Chart.yaml").write_text(chart_yaml, encoding="utf-8")
        (output_dir / "values.yaml").write_text(values_yaml, encoding="utf-8")
        for name, content in templates.items():
            (templates_dir / name).write_text(content, encoding="utf-8")

        return HelmChart(chart_yaml=chart_yaml, values_yaml=values_yaml, templates=templates)

    def _deployment_template(self, config: DeploymentConfig) -> str:
        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "archon-api"},
            "spec": {
                "replicas": max(1, int(config.replicas)),
                "selector": {"matchLabels": {"app": "archon-api"}},
                "template": {
                    "metadata": {"labels": {"app": "archon-api"}},
                    "spec": {
                        "containers": [
                            {
                                "name": "archon-api",
                                "image": "ghcr.io/archon/api:0.1.0",
                                "ports": [{"containerPort": 8000}],
                                "envFrom": [
                                    {"configMapRef": {"name": "archon-config"}},
                                    {"secretRef": {"name": "archon-secret"}},
                                ],
                            }
                        ]
                    },
                },
            },
        }
        return yaml.safe_dump(deployment, sort_keys=False)

    def _service_template(self, config: DeploymentConfig) -> str:
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "archon-api"},
            "spec": {
                "selector": {"app": "archon-api"},
                "ports": [{"port": 80, "targetPort": 8000}],
                "type": "ClusterIP",
            },
        }
        return yaml.safe_dump(service, sort_keys=False)

    def _ingress_template(self, config: DeploymentConfig) -> str:
        annotations = {}
        if config.tls:
            annotations["cert-manager.io/cluster-issuer"] = "letsencrypt-prod"
        ingress = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {"name": "archon", "annotations": annotations},
            "spec": {
                "rules": [
                    {
                        "host": config.domain or "archon.local",
                        "http": {
                            "paths": [
                                {
                                    "path": "/",
                                    "pathType": "Prefix",
                                    "backend": {
                                        "service": {"name": "archon-api", "port": {"number": 80}}
                                    },
                                }
                            ]
                        },
                    }
                ]
            },
        }
        if config.tls:
            ingress["spec"]["tls"] = [
                {"hosts": [config.domain or "archon.local"], "secretName": "archon-tls"}
            ]
        return yaml.safe_dump(ingress, sort_keys=False)

    def _configmap_template(self, config: DeploymentConfig) -> str:
        configmap = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "archon-config"},
            "data": {
                "ARCHON_TENANT_ID": config.tenant_id,
                "ARCHON_TIER": config.tier,
                "SMTP_HOST": config.smtp_host or "smtp",
                "REDIS_URL": config.redis_url or "redis://redis:6379/0",
            },
        }
        return yaml.safe_dump(configmap, sort_keys=False)

    def _secret_template(self, config: DeploymentConfig) -> str:
        payload = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "archon-secret"},
            "type": "Opaque",
            "data": {
                "ARCHON_MASTER_KEY": _b64("ARCHON_MASTER_KEY"),
                "DATABASE_URL": _b64(
                    config.external_db_url or "postgresql://archon:archon@postgres:5432/archon"
                ),
                "SMTP_HOST": _b64(config.smtp_host or "smtp"),
            },
        }
        return yaml.safe_dump(payload, sort_keys=False)

    def _hpa_template(self, config: DeploymentConfig) -> str:
        hpa = {
            "apiVersion": "autoscaling/v2",
            "kind": "HorizontalPodAutoscaler",
            "metadata": {"name": "archon-api"},
            "spec": {
                "scaleTargetRef": {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": "archon-api",
                },
                "minReplicas": 1,
                "maxReplicas": max(1, int(config.replicas)),
                "metrics": [
                    {
                        "type": "Resource",
                        "resource": {
                            "name": "cpu",
                            "target": {"type": "Utilization", "averageUtilization": 70},
                        },
                    }
                ],
            },
        }
        return yaml.safe_dump(hpa, sort_keys=False)

    def _pdb_template(self) -> str:
        pdb = {
            "apiVersion": "policy/v1",
            "kind": "PodDisruptionBudget",
            "metadata": {"name": "archon-api"},
            "spec": {"minAvailable": 1, "selector": {"matchLabels": {"app": "archon-api"}}},
        }
        return yaml.safe_dump(pdb, sort_keys=False)


def _b64(value: str) -> str:
    return base64.b64encode(str(value).encode("utf-8")).decode("ascii")
