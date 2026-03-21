"""ARCHON command line interface bindings and entrypoint."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import click
import httpx
import yaml

from archon.api.auth import create_tenant_token
from archon.config import ArchonConfig, load_archon_config
from archon.deploy.cli import deploy_group
from archon.validate_config import main as validate_config_main
from archon.versioning import resolve_git_sha, resolve_version

DEFAULT_CONFIG_PATH = "config.archon.yaml"
DEFAULT_SERVER_URL = "http://127.0.0.1:8000"


def _load_config(path: str = DEFAULT_CONFIG_PATH) -> ArchonConfig:
    return load_archon_config(path)


def write_env(key: str, value: str, env_path: str | Path = ".env") -> None:
    """Upsert a key=value line in .env file."""

    if key and value:
        os.environ[key] = value
    path = Path(env_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated = False
    output: list[str] = []
    prefix = f"{key}="
    for line in lines:
        if line.startswith(prefix):
            if not updated:
                output.append(f"{key}={value}")
                updated = True
            continue
        output.append(line)
    if not updated:
        output.append(f"{key}={value}")
    path.write_text("\n".join(output).rstrip("\n") + "\n", encoding="utf-8")


def _read_env_value(key: str, env_path: str | Path = ".env") -> str | None:
    path = Path(env_path)
    if not path.exists():
        return None
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _load_env_file(env_path: str | Path = ".env") -> None:
    path = Path(env_path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _default_byok_config() -> dict[str, Any]:
    defaults_path = "__wizard_defaults__.yaml"
    if Path(defaults_path).exists():
        return load_archon_config(defaults_path).byok.model_dump()
    return ArchonConfig().byok.model_dump()


def _probe_ollama(timeout_s: float = 2.0) -> dict[str, Any]:
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=timeout_s)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return {"reachable": False, "models": [], "detail": "unreachable"}

    models: list[str] = []
    raw_models = payload.get("models", [])
    if isinstance(raw_models, list):
        for item in raw_models:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("model") or "").strip()
            else:
                name = str(item).strip()
            if name:
                models.append(name)
    return {"reachable": True, "models": models, "detail": "reachable"}


def _validate_openrouter_key(api_key: str, timeout_s: float = 5.0) -> bool:
    try:
        response = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
        )
        return response.is_success
    except httpx.HTTPError:
        return False


def _validate_openai_key(api_key: str, timeout_s: float = 5.0) -> bool:
    try:
        response = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
        )
        return response.is_success
    except httpx.HTTPError:
        return False


def _validate_anthropic_key(api_key: str, timeout_s: float = 5.0) -> bool:
    try:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-5-haiku-latest",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=timeout_s,
        )
        return response.is_success
    except httpx.HTTPError:
        return False


def _validation_payload(config_data: dict[str, Any]) -> dict[str, Any]:
    byok = dict(config_data.get("byok") or {})
    budget = dict(config_data.get("budget") or {})
    daily_limit = float(budget.get("daily_limit_usd", 5.0) or 5.0)
    alert_threshold_pct = int(budget.get("alert_threshold_pct", 80) or 80)
    return {
        "providers": {
            "primary": byok.get("primary", "anthropic"),
            "coding": byok.get("coding", "openai"),
            "vision": byok.get("vision", "openai"),
            "fast": byok.get("fast", "groq"),
            "embedding": byok.get("embedding", "ollama"),
            "fallback": byok.get("fallback", "openrouter"),
            "ollama_base_url": byok.get("ollama_base_url", "http://localhost:11434/v1"),
            "openrouter_base_url": byok.get("openrouter_base_url", "https://openrouter.ai/api/v1"),
            "custom_endpoints": list(byok.get("custom_endpoints", [])),
        },
        "budget": {
            "per_request_usd": float(byok.get("budget_per_task_usd", 0.50) or 0.50),
            "daily_usd": daily_limit,
            "monthly_usd": float(byok.get("budget_per_month_usd", round(daily_limit * 30.0, 2))),
            "alert_threshold": round(alert_threshold_pct / 100.0, 4),
        },
        "tenants": [],
        "memory": {"backend": "sqlite"},
        "evolution": {"enabled": False, "max_experiments_per_day": 0},
        "skills": {
            "enabled": bool((config_data.get("skills") or {}).get("enabled", True)),
            "auto_propose": bool((config_data.get("skills") or {}).get("auto_propose", False)),
            "staging_threshold": float(
                (config_data.get("skills") or {}).get("staging_threshold", 0.75)
            ),
        },
    }


def _run_validation(config_data: dict[str, Any], config_path: str) -> int:
    temp_path: Path | None = None
    try:
        config_dir = Path(config_path).resolve().parent
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".yaml",
            delete=False,
            dir=str(config_dir),
        ) as handle:
            yaml.safe_dump(_validation_payload(config_data), handle, sort_keys=False)
            temp_path = Path(handle.name)
        with io.StringIO() as stdout_buffer, io.StringIO() as stderr_buffer:
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                return int(validate_config_main(["--config", str(temp_path)]))
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _save_onboarding_config(config_data: dict[str, Any], config_path: str) -> None:
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(config_data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _normalize_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip()
    if not normalized:
        return DEFAULT_SERVER_URL
    return normalized.rstrip("/")


def _create_api_headers(
    *,
    token: str | None = None,
    tenant_id: str = "default",
    tier: str = "pro",
) -> dict[str, str]:
    resolved = str(token or "").strip()
    if not resolved:
        resolved = create_tenant_token(tenant_id=tenant_id, tier=tier)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {resolved}"}


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout_s: float = 30.0,
) -> Any:
    response = httpx.request(
        method=method.upper(),
        url=url,
        headers=headers,
        json=json_body,
        timeout=timeout_s,
    )
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def _request_text(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_s: float = 30.0,
) -> str:
    response = httpx.request(
        method=method.upper(),
        url=url,
        headers=headers,
        timeout=timeout_s,
    )
    response.raise_for_status()
    return response.text


def _parse_context(
    context_text: str | None,
    context_file: Path | None,
) -> dict[str, Any]:
    if context_text and context_file is not None:
        raise click.ClickException("Use either --context or --context-file, not both.")
    if context_file is not None:
        with context_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    elif context_text:
        payload = json.loads(context_text)
    else:
        return {}
    if not isinstance(payload, dict):
        raise click.ClickException("Task context must decode to a JSON object.")
    return payload


def _resolve_version() -> str:
    return resolve_version()


def _resolve_git_sha() -> str:
    return resolve_git_sha()


def _run_api_server_with_env(*, host: str, port: int) -> None:
    previous_host = os.environ.get("ARCHON_HOST")
    previous_port = os.environ.get("ARCHON_PORT")
    os.environ["ARCHON_HOST"] = host
    os.environ["ARCHON_PORT"] = str(port)
    try:
        from archon.interfaces.api.server import run as run_api_server

        run_api_server()
    finally:
        if previous_host is None:
            os.environ.pop("ARCHON_HOST", None)
        else:
            os.environ["ARCHON_HOST"] = previous_host
        if previous_port is None:
            os.environ.pop("ARCHON_PORT", None)
        else:
            os.environ["ARCHON_PORT"] = previous_port


@click.group()
def legacy_cli() -> None:
    """Compatibility commands that live outside drawers."""


legacy_cli.add_command(deploy_group)


@legacy_cli.command("version")
def version_command() -> None:
    """Print ARCHON version + git sha."""

    click.echo(f"ARCHON {_resolve_version()} (git {_resolve_git_sha()})")


def _build_root_cli() -> click.Group:
    from archon.cli.main import build_cli

    return build_cli(sys.modules[__name__])  # type: ignore[name-defined]


cli = _build_root_cli()


def main() -> None:
    """Entry point for `python -m archon.archon_cli`."""

    _load_env_file()
    cli(prog_name="archon")


if __name__ == "__main__":
    main()
