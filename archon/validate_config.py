"""ARCHON config validation CLI with provider health checks."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

from pydantic import ValidationError

from archon.config import SUPPORTED_PROVIDERS, ArchonConfig, load_archon_config
from archon.providers import ProviderRouter
from archon.providers.router import PROVIDER_ENV_KEY, ProviderUnavailableError

ROLE_NAMES = ("primary", "coding", "vision", "fast", "embedding")


@dataclass(slots=True)
class ProviderHealth:
    """Health status for one configured role/provider."""

    role: str
    configured_provider: str
    resolved_provider: str | None
    resolved_model: str | None
    status: str
    detail: str = ""


@dataclass(slots=True)
class ValidationReport:
    """Serializable validation report for CLI output."""

    config_path: str
    dry_run: bool
    schema_valid: bool
    role_health: list[ProviderHealth] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.schema_valid and not self.errors

    def to_json(self) -> str:
        return json.dumps(
            {
                "config_path": self.config_path,
                "dry_run": self.dry_run,
                "schema_valid": self.schema_valid,
                "ok": self.ok,
                "role_health": [asdict(item) for item in self.role_health],
                "warnings": self.warnings,
                "errors": self.errors,
            },
            indent=2,
        )


def validate_config(
    path: str | Path = "config.archon.yaml", *, dry_run: bool = False
) -> ValidationReport:
    """Validate ARCHON config schema and runtime provider resolvability."""

    config_path = Path(path)
    report = ValidationReport(
        config_path=str(config_path),
        dry_run=dry_run,
        schema_valid=False,
    )

    try:
        config = load_archon_config(config_path)
        report.schema_valid = True
    except ValidationError as exc:
        report.errors.append(f"Schema validation failed: {exc}")
        return report
    except Exception as exc:  # pragma: no cover - defensive guard
        report.errors.append(f"Unable to read config: {exc}")
        return report

    report.warnings.extend(_validate_provider_names(config))
    report.warnings.extend(_validate_custom_endpoint_urls(config))

    router = ProviderRouter(config=config, live_mode=False)
    try:
        for role in ROLE_NAMES:
            configured_provider = _configured_provider_for_role(config, role)
            try:
                selection = router.resolve_provider(role=role)
                report.role_health.append(
                    ProviderHealth(
                        role=role,
                        configured_provider=configured_provider,
                        resolved_provider=selection.provider,
                        resolved_model=selection.model,
                        status="ok",
                        detail=f"Resolved via {selection.source}",
                    )
                )
            except ProviderUnavailableError as exc:
                detail = str(exc)
                missing_key_resolution = "Missing keys:" in detail
                is_error = not dry_run or not missing_key_resolution
                report.role_health.append(
                    ProviderHealth(
                        role=role,
                        configured_provider=configured_provider,
                        resolved_provider=None,
                        resolved_model=None,
                        status="error" if is_error else "warning",
                        detail=detail,
                    )
                )
                if is_error:
                    report.errors.append(f"Role '{role}' is not resolvable: {exc}")
                else:
                    report.warnings.append(f"Role '{role}' unresolved in dry-run: {exc}")

        credential_findings = _credential_health(config)
        if dry_run:
            report.warnings.extend(credential_findings)
        else:
            report.errors.extend(credential_findings)
    finally:
        # Keep cleanup deterministic even in validation-only mode.
        import asyncio

        asyncio.run(router.aclose())

    return report


def _configured_provider_for_role(config: ArchonConfig, role: str) -> str:
    byok = config.byok
    if role == "embedding":
        return "ollama"
    return getattr(byok, role, byok.primary)


def _validate_provider_names(config: ArchonConfig) -> list[str]:
    warnings: list[str] = []
    custom_names = {endpoint.name for endpoint in config.byok.custom_endpoints}
    for role in ("primary", "coding", "vision", "fast", "fallback"):
        value = getattr(config.byok, role)
        if value not in SUPPORTED_PROVIDERS and value not in custom_names:
            warnings.append(
                f"Role '{role}' references unknown provider '{value}'. "
                "It must match a built-in provider or custom endpoint name."
            )
    return warnings


def _validate_custom_endpoint_urls(config: ArchonConfig) -> list[str]:
    warnings: list[str] = []
    for endpoint in config.byok.custom_endpoints:
        parsed = urlparse(endpoint.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            warnings.append(
                f"Custom endpoint '{endpoint.name}' has invalid base_url '{endpoint.base_url}'."
            )
    return warnings


def _credential_health(config: ArchonConfig) -> list[str]:
    missing: list[str] = []
    providers = _providers_needed_for_resolution(config)
    for provider in sorted(providers):
        if provider == "ollama":
            continue
        env_name = PROVIDER_ENV_KEY.get(provider)
        if env_name and not os.environ.get(env_name):
            missing.append(f"Missing credential for provider '{provider}' ({env_name}).")
    return missing


def _providers_needed_for_resolution(config: ArchonConfig) -> set[str]:
    providers: set[str] = set()
    byok = config.byok
    custom_names = {endpoint.name for endpoint in byok.custom_endpoints}

    for role in ROLE_NAMES:
        provider_name = _configured_provider_for_role(config, role)
        if provider_name in custom_names:
            providers.add("custom")
            continue
        providers.add(provider_name)
        fallback = byok.fallback
        if fallback and fallback not in custom_names:
            providers.add(fallback)

    return {name for name in providers if name != "custom"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate ARCHON config and provider health.")
    parser.add_argument(
        "--config",
        default="config.archon.yaml",
        help="Path to ARCHON YAML config file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report missing credentials as warnings instead of errors.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run validate-config CLI and return process exit code."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    report = validate_config(path=args.config, dry_run=args.dry_run)

    if args.json:
        print(report.to_json())
    else:
        print(f"Config file: {report.config_path}")
        print(f"Schema valid: {report.schema_valid}")
        for item in report.role_health:
            status = item.status.upper()
            print(
                f"[{status}] role={item.role} configured={item.configured_provider} "
                f"resolved={item.resolved_provider or '-'} model={item.resolved_model or '-'}"
            )
            if item.detail:
                print(f"  detail: {item.detail}")
        for warning in report.warnings:
            print(f"[WARN] {warning}")
        for error in report.errors:
            print(f"[ERROR] {error}")
        print("Validation: PASS" if report.ok else "Validation: FAIL")

    return 0 if report.ok else 1


def run() -> None:
    """Console entrypoint for `python -m archon.validate_config`."""

    raise SystemExit(main())


if __name__ == "__main__":
    run()
