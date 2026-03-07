"""Live deployment validator for ARCHON on-prem installs."""

from __future__ import annotations

import argparse
import ssl
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from archon.interfaces.webchat.auth import verify_webchat_token
from archon.onprem.compose_generator import DeploymentConfig


@dataclass(slots=True, frozen=True)
class ValidationCheck:
    """One deployment validation check result.

    Example:
        >>> ValidationCheck("api_reachable", True, "ok", "critical").passed
        True
    """

    name: str
    passed: bool
    message: str
    severity: str


@dataclass(slots=True, frozen=True)
class ValidationReport:
    """Aggregate validation report.

    Example:
        >>> ValidationReport([], 0, 0, []).failed_count
        0
    """

    checks: list[ValidationCheck]
    passed_count: int
    failed_count: int
    blocking_failures: list[ValidationCheck]


class DeployValidator:
    """Validate a deployment before production cutover.

    Example:
        >>> validator = DeployValidator(http_client=httpx.Client())
        >>> isinstance(validator.http_client, httpx.Client)
        True
    """

    def __init__(self, *, http_client: httpx.Client | None = None) -> None:
        self.http_client = http_client or httpx.Client(timeout=10.0)

    def run_all(self, config: DeploymentConfig, base_url: str) -> ValidationReport:
        """Run all deployment checks and summarize failures.

        Example:
            >>> validator = DeployValidator(http_client=httpx.Client())
            >>> report = validator.run_all(DeploymentConfig("tenant-a", "enterprise", False, [], "", "", "", "", False, 1), "https://example.com")
            >>> isinstance(report.checks, list)
            True
        """

        checks = [
            self._check_api_reachable(base_url),
            self._check_auth_working(base_url),
            self._check_db_connected(base_url),
            self._check_ollama_reachable(config),
            self._check_ssl_valid(config, base_url),
            self._check_config_valid(),
        ]
        filtered = [check for check in checks if check is not None]
        blocking = [
            check for check in filtered if check.severity == "critical" and not check.passed
        ]
        return ValidationReport(
            checks=filtered,
            passed_count=sum(1 for check in filtered if check.passed),
            failed_count=sum(1 for check in filtered if not check.passed),
            blocking_failures=blocking,
        )

    def _check_api_reachable(self, base_url: str) -> ValidationCheck:
        try:
            response = self.http_client.get(f"{base_url.rstrip('/')}/health")
            if response.status_code == 200:
                return ValidationCheck("api_reachable", True, "API returned 200.", "critical")
            return ValidationCheck(
                "api_reachable",
                False,
                f"Unexpected status {response.status_code}.",
                "critical",
            )
        except Exception as exc:
            return ValidationCheck("api_reachable", False, str(exc), "critical")

    def _check_auth_working(self, base_url: str) -> ValidationCheck:
        try:
            response = self.http_client.post(f"{base_url.rstrip('/')}/webchat/token", json={})
            if response.status_code != 200:
                return ValidationCheck(
                    "auth_working",
                    False,
                    f"Unexpected status {response.status_code}.",
                    "critical",
                )
            payload = response.json()
            token = str(payload.get("token") or "")
            if not token:
                return ValidationCheck(
                    "auth_working", False, "Token missing from response.", "critical"
                )
            verify_webchat_token(token)
            return ValidationCheck("auth_working", True, "Webchat token verified.", "critical")
        except Exception as exc:
            return ValidationCheck("auth_working", False, str(exc), "critical")

    def _check_db_connected(self, base_url: str) -> ValidationCheck:
        try:
            response = self.http_client.get(f"{base_url.rstrip('/')}/health")
            payload = response.json()
            passed = response.status_code == 200 and str(payload.get("db_status") or "") == "ok"
            return ValidationCheck(
                "db_connected",
                passed,
                "Database status is ok."
                if passed
                else "Database health check did not return db_status=ok.",
                "critical",
            )
        except Exception as exc:
            return ValidationCheck("db_connected", False, str(exc), "critical")

    def _check_ollama_reachable(self, config: DeploymentConfig) -> ValidationCheck | None:
        if not config.ollama_models:
            return None
        base_url = "http://localhost:11434"
        try:
            response = self.http_client.get(f"{base_url}/api/tags")
            return ValidationCheck(
                "ollama_reachable",
                response.status_code == 200,
                "Ollama responded to /api/tags."
                if response.status_code == 200
                else f"Unexpected status {response.status_code}.",
                "warning",
            )
        except Exception as exc:
            return ValidationCheck("ollama_reachable", False, str(exc), "warning")

    def _check_ssl_valid(self, config: DeploymentConfig, base_url: str) -> ValidationCheck | None:
        if not config.tls:
            return None
        try:
            expiry = _ssl_certificate_expiry(base_url)
            remaining_days = (expiry - datetime.now(timezone.utc)).total_seconds() / 86400
            passed = remaining_days > 30
            return ValidationCheck(
                "ssl_valid",
                passed,
                f"Certificate expires in {remaining_days:.1f} days.",
                "critical",
            )
        except Exception as exc:
            return ValidationCheck("ssl_valid", False, str(exc), "critical")

    def _check_config_valid(self) -> ValidationCheck:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "archon.validate_config", "--dry-run"],
                capture_output=True,
                text=True,
                check=False,
            )
            passed = int(result.returncode) == 0
            detail = result.stdout.strip() or result.stderr.strip() or "No output."
            return ValidationCheck("config_valid", passed, detail, "critical")
        except Exception as exc:
            return ValidationCheck("config_valid", False, str(exc), "critical")


def _ssl_certificate_expiry(base_url: str) -> datetime:
    parsed = urlparse(base_url)
    hostname = parsed.hostname or "localhost"
    port = int(parsed.port or 443)
    context = ssl.create_default_context()
    with context.wrap_socket(
        __import__("socket").create_connection((hostname, port)), server_hostname=hostname
    ) as sock:
        cert = sock.getpeercert()
    not_after = str(cert.get("notAfter") or "")
    return datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for deployment validation.

    Example:
        >>> isinstance(main(["--url", "https://example.com"]), int)
        True
    """

    parser = argparse.ArgumentParser(prog="python -m archon.onprem.validator")
    parser.add_argument("--url", required=True)
    parser.add_argument("--tenant-id", default="tenant-onprem")
    parser.add_argument("--tier", default="enterprise")
    parser.add_argument("--replicas", type=int, default=1)
    parser.add_argument("--tls", action="store_true", default=False)
    args = parser.parse_args(argv)

    config = DeploymentConfig(
        tenant_id=args.tenant_id,
        tier=args.tier,
        enable_gpu=False,
        ollama_models=[],
        external_db_url="",
        smtp_host="",
        redis_url="",
        domain=urlparse(args.url).hostname or "",
        tls=bool(args.tls),
        replicas=max(1, int(args.replicas)),
    )
    validator = DeployValidator()
    report = validator.run_all(config, args.url)
    for check in report.checks:
        print(f"{check.name}: {check.passed} [{check.severity}] {check.message}")
    return 0 if not report.blocking_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
