"""Docker Compose manifest generator for ARCHON on-prem deployments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

PINNED_IMAGES = {
    "archon-api": "ghcr.io/archon/api@sha256:1111111111111111111111111111111111111111111111111111111111111111",
    "archon-webchat": "ghcr.io/archon/webchat@sha256:2222222222222222222222222222222222222222222222222222222222222222",
    "archon-worker": "ghcr.io/archon/worker@sha256:3333333333333333333333333333333333333333333333333333333333333333",
    "postgres": "postgres@sha256:4444444444444444444444444444444444444444444444444444444444444444",
    "redis": "redis@sha256:5555555555555555555555555555555555555555555555555555555555555555",
    "ollama": "ollama/ollama@sha256:6666666666666666666666666666666666666666666666666666666666666666",
    "nginx": "nginx@sha256:7777777777777777777777777777777777777777777777777777777777777777",
}


@dataclass(slots=True)
class DeploymentConfig:
    """On-prem deployment configuration.

    Example:
        >>> DeploymentConfig(tenant_id="tenant-a", tier="enterprise", enable_gpu=False, ollama_models=[], external_db_url="", smtp_host="", redis_url="", domain="", tls=False, replicas=2).tenant_id
        'tenant-a'
    """

    tenant_id: str
    tier: str
    enable_gpu: bool
    ollama_models: list[str]
    external_db_url: str
    smtp_host: str
    redis_url: str
    domain: str
    tls: bool
    replicas: int


@dataclass(slots=True)
class ComposeManifest:
    """Structured docker-compose output.

    Example:
        >>> ComposeManifest(yaml_str="services: {}", services={}, volumes={}, networks={}).yaml_str.startswith("services")
        True
    """

    yaml_str: str
    services: dict[str, Any]
    volumes: dict[str, Any]
    networks: dict[str, Any]


class DockerComposeGenerator:
    """Generate a pinned docker-compose manifest for one deployment config.

    Example:
        >>> generator = DockerComposeGenerator()
        >>> generator.generate(DeploymentConfig("tenant-a", "enterprise", False, [], "", "", "", "", False, 1)).services["archon-api"]["image"].startswith("ghcr.io/archon/api@sha256:")
        True
    """

    def generate(self, config: DeploymentConfig) -> ComposeManifest:
        """Build the docker-compose manifest.

        Example:
            >>> generator = DockerComposeGenerator()
            >>> manifest = generator.generate(DeploymentConfig("tenant-a", "enterprise", False, [], "", "", "", "", False, 1))
            >>> "archon-api" in manifest.services
            True
        """

        env_file = [".env.archon"]
        internal_networks = ["archon-internal"]
        services: dict[str, Any] = {
            "archon-api": {
                "image": PINNED_IMAGES["archon-api"],
                "env_file": env_file,
                "environment": {
                    "ARCHON_TENANT_ID": config.tenant_id,
                    "ARCHON_TIER": config.tier,
                    "DATABASE_URL": config.external_db_url
                    or "postgresql://archon:archon@postgres:5432/archon",
                    "REDIS_URL": config.redis_url or "redis://redis:6379/0",
                    "SMTP_HOST": config.smtp_host or "smtp",
                },
                "depends_on": ["postgres", "redis"],
                "networks": list(internal_networks),
                "restart": "unless-stopped",
            },
            "archon-webchat": {
                "image": PINNED_IMAGES["archon-webchat"],
                "env_file": env_file,
                "environment": {"ARCHON_API_BASE_URL": "http://archon-api:8000"},
                "depends_on": ["archon-api"],
                "networks": list(internal_networks),
                "restart": "unless-stopped",
            },
            "archon-worker": {
                "image": PINNED_IMAGES["archon-worker"],
                "env_file": env_file,
                "environment": {
                    "DATABASE_URL": config.external_db_url
                    or "postgresql://archon:archon@postgres:5432/archon",
                    "REDIS_URL": config.redis_url or "redis://redis:6379/0",
                },
                "depends_on": ["postgres", "redis"],
                "networks": list(internal_networks),
                "restart": "unless-stopped",
            },
            "postgres": {
                "image": PINNED_IMAGES["postgres"],
                "environment": {
                    "POSTGRES_DB": "archon",
                    "POSTGRES_USER": "archon",
                    "POSTGRES_PASSWORD": "archon",
                },
                "volumes": ["postgres-data:/var/lib/postgresql/data"],
                "networks": list(internal_networks),
                "restart": "unless-stopped",
            },
            "redis": {
                "image": PINNED_IMAGES["redis"],
                "command": ["redis-server", "--appendonly", "yes"],
                "volumes": ["redis-data:/data"],
                "networks": list(internal_networks),
                "restart": "unless-stopped",
            },
        }
        services["archon-api"]["volumes"] = [
            "archon-data:/var/lib/archon",
            "archon-memory:/var/lib/archon/memory",
        ]
        services["archon-worker"]["volumes"] = [
            "archon-data:/var/lib/archon",
            "archon-memory:/var/lib/archon/memory",
        ]

        if config.ollama_models:
            services["ollama"] = {
                "image": PINNED_IMAGES["ollama"],
                "env_file": env_file,
                "environment": {"OLLAMA_MODELS": ",".join(config.ollama_models)},
                "volumes": ["archon-data:/root/.ollama"],
                "networks": list(internal_networks),
                "restart": "unless-stopped",
            }
            services["archon-api"]["depends_on"].append("ollama")
            services["archon-worker"]["depends_on"].append("ollama")

        if config.enable_gpu and "ollama" in services:
            services["ollama"]["deploy"] = {
                "resources": {
                    "reservations": {
                        "devices": [{"driver": "nvidia", "count": 1, "capabilities": ["gpu"]}]
                    }
                }
            }

        networks = {
            "archon-internal": {"driver": "bridge", "internal": True},
            "archon-public": {"driver": "bridge"},
        }

        if config.domain:
            services["nginx"] = {
                "image": PINNED_IMAGES["nginx"],
                "env_file": env_file,
                "depends_on": ["archon-api", "archon-webchat"],
                "ports": ["80:80", "443:443"] if config.tls else ["80:80"],
                "environment": {
                    "ARCHON_DOMAIN": config.domain,
                    "ARCHON_TLS": "true" if config.tls else "false",
                },
                "networks": ["archon-public", "archon-internal"],
                "restart": "unless-stopped",
            }
            services["archon-api"]["networks"] = ["archon-internal", "archon-public"]

        volumes = {
            "archon-data": {},
            "archon-memory": {},
            "postgres-data": {},
            "redis-data": {},
        }

        manifest = {
            "version": "3.9",
            "services": services,
            "volumes": volumes,
            "networks": networks,
        }
        yaml_str = yaml.safe_dump(manifest, sort_keys=False)
        return ComposeManifest(
            yaml_str=yaml_str,
            services=services,
            volumes=volumes,
            networks=networks,
        )
