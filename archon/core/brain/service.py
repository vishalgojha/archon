"""Schema-validated brain artifact storage."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

ARTIFACT_SCHEMAS: dict[str, str] = {
    "module_registry": "module_registry.schema.json",
    "architecture": "architecture.schema.json",
}
SNAPSHOT_ARTIFACTS: dict[str, str] = {
    "reality_snapshot": "reality_snapshot.json",
    "delta": "delta.json",
}


@dataclass(frozen=True)
class BrainConfig:
    active_schema_version: str
    ownership: dict[str, set[str]]
    config_dir: Path
    schema_root: Path


class BrainArtifactError(ValueError):
    def __init__(self, *, artifact: str, allowed: Iterable[str], message: str) -> None:
        super().__init__(message)
        self.artifact = artifact
        self.allowed = sorted(set(allowed))
        self.message = message

    def to_error(self) -> dict[str, Any]:
        return {
            "code": "unknown_artifact",
            "message": self.message,
            "artifact": self.artifact,
            "allowed": self.allowed,
        }


class BrainVersionMismatchError(ValueError):
    def __init__(self, *, requested: str, active: str) -> None:
        super().__init__("Schema version mismatch.")
        self.requested = requested
        self.active = active

    def to_error(self) -> dict[str, Any]:
        return {
            "code": "schema_version_mismatch",
            "message": "Schema version mismatch.",
            "requested": self.requested,
            "active": self.active,
        }


class BrainUnauthorizedError(PermissionError):
    def __init__(self, *, artifact: str, agent_id: str) -> None:
        super().__init__("Agent not authorized to write artifact.")
        self.artifact = artifact
        self.agent_id = agent_id

    def to_error(self) -> dict[str, Any]:
        return {
            "code": "unauthorized_agent",
            "message": "Agent is not authorized to write this artifact.",
            "artifact": self.artifact,
            "agent_id": self.agent_id,
        }


class BrainSchemaViolation(ValueError):
    def __init__(self, *, artifact: str, schema_version: str, errors: list[dict[str, Any]]):
        super().__init__("Payload failed schema validation.")
        self.artifact = artifact
        self.schema_version = schema_version
        self.errors = errors

    def to_error(self) -> dict[str, Any]:
        return {
            "code": "schema_validation_error",
            "message": "Payload failed schema validation.",
            "artifact": self.artifact,
            "schema_version": self.schema_version,
            "errors": self.errors,
        }


def _resolve_brain_root(default_dir: str = "brain") -> Path:
    env_root = str(os.getenv("ARCHON_BRAIN_ROOT", "")).strip()
    if env_root:
        return Path(env_root)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / default_dir


def resolve_brain_root() -> Path:
    return _resolve_brain_root()


def _resolve_config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "brain" / "config"


def _resolve_schema_root() -> Path:
    return Path(__file__).resolve().parents[2] / "brain" / "schema"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing brain config file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_brain_config(config_dir: Path | None = None) -> BrainConfig:
    config_root = config_dir or _resolve_config_dir()
    schema_root = _resolve_schema_root()
    active_schema_path = config_root / "active_schema.json"
    ownership_path = config_root / "ownership.json"
    active_schema = _load_json(active_schema_path)
    ownership_raw = _load_json(ownership_path)
    active_version = str(active_schema.get("active_version", "")).strip()
    if not active_version:
        raise ValueError("active_schema.json missing active_version.")
    ownership: dict[str, set[str]] = {}
    if isinstance(ownership_raw, dict):
        for artifact, owners in ownership_raw.items():
            if isinstance(owners, list):
                ownership[str(artifact)] = {str(owner) for owner in owners if owner}
    return BrainConfig(
        active_schema_version=active_version,
        ownership=ownership,
        config_dir=config_root,
        schema_root=schema_root,
    )


def _error_from_jsonschema(error: Exception) -> dict[str, Any]:
    try:
        from jsonschema.exceptions import ValidationError

        if isinstance(error, ValidationError):
            path = "/" + "/".join(str(part) for part in error.path)
            schema_path = "/" + "/".join(str(part) for part in error.schema_path)
            return {
                "path": path,
                "message": error.message,
                "validator": str(error.validator),
                "schema_path": schema_path,
            }
    except Exception:
        pass
    return {"path": "", "message": str(error), "validator": "unknown", "schema_path": ""}


class BrainService:
    def __init__(self, config: BrainConfig, root: Path | None = None) -> None:
        self._config = config
        self._root = root or resolve_brain_root()
        self._schema_cache: dict[str, dict[str, Any]] = {}

    @property
    def config(self) -> BrainConfig:
        return self._config

    @property
    def root(self) -> Path:
        return self._root

    def _schema_path(self, artifact: str) -> Path:
        filename = ARTIFACT_SCHEMAS.get(artifact)
        if not filename:
            raise BrainArtifactError(
                artifact=artifact,
                allowed=ARTIFACT_SCHEMAS.keys(),
                message="Artifact is not supported for schema validation.",
            )
        return self._config.schema_root / self._config.active_schema_version / filename

    def _load_schema(self, artifact: str) -> dict[str, Any]:
        if artifact in self._schema_cache:
            return self._schema_cache[artifact]
        path = self._schema_path(artifact)
        schema = _load_json(path)
        self._schema_cache[artifact] = schema
        return schema

    def _check_version(self, requested: str) -> None:
        if requested != self._config.active_schema_version:
            raise BrainVersionMismatchError(
                requested=requested, active=self._config.active_schema_version
            )

    def _check_ownership(self, artifact: str, agent_id: str) -> None:
        allowed = self._config.ownership.get(artifact, set())
        if agent_id not in allowed:
            raise BrainUnauthorizedError(artifact=artifact, agent_id=agent_id)

    def _validate_schema(self, artifact: str, payload: dict[str, Any]) -> None:
        schema = self._load_schema(artifact)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
        if errors:
            formatted = [_error_from_jsonschema(error) for error in errors]
            raise BrainSchemaViolation(
                artifact=artifact,
                schema_version=self._config.active_schema_version,
                errors=formatted,
            )

    def write(
        self, *, artifact: str, schema_version: str, agent_id: str, payload: dict[str, Any]
    ) -> Path:
        if artifact not in ARTIFACT_SCHEMAS:
            raise BrainArtifactError(
                artifact=artifact,
                allowed=ARTIFACT_SCHEMAS.keys(),
                message="Artifact is not supported for schema validation.",
            )
        self._check_version(schema_version)
        self._check_ownership(artifact, agent_id)
        self._validate_schema(artifact, payload)
        path = self._root / f"{artifact}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def snapshot(self, *, artifact: str, payload: dict[str, Any]) -> Path:
        filename = SNAPSHOT_ARTIFACTS.get(artifact)
        if not filename:
            raise BrainArtifactError(
                artifact=artifact,
                allowed=SNAPSHOT_ARTIFACTS.keys(),
                message="Artifact is not supported for snapshot writes.",
            )
        path = self._root / "snapshots" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path
