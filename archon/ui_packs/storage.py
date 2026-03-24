"""UI pack storage loader and integrity validator."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACK_SCHEMA_VERSION = 1
_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


class UIPackError(RuntimeError):
    """UI pack storage error. Example: `raise UIPackError("missing pack")`."""


@dataclass(frozen=True, slots=True)
class UIPackDescriptor:
    """Normalized UI pack descriptor loaded from `pack.json`."""

    tenant_id: str
    version: str
    entrypoint: str
    manifest: dict[str, Any]
    assets: dict[str, dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = PACK_SCHEMA_VERSION
    pack_root: Path = field(default_factory=Path)


class UIPackStorage:
    """Filesystem-backed UI pack store.

    Example:
        >>> storage = UIPackStorage(root="ui_packs")
        >>> storage.resolve_pack_dir("tenant-1", "v1")
        PosixPath('ui_packs/tenant-1/v1')
    """

    def __init__(self, root: str | Path) -> None:
        """Create a storage handle.

        Example:
            >>> UIPackStorage(root="ui_packs").root.name
            'ui_packs'
        """

        self.root = Path(root)

    def resolve_pack_dir(self, tenant_id: str, version: str) -> Path:
        """Resolve a pack directory rooted under storage.

        Example:
            >>> UIPackStorage("ui_packs").resolve_pack_dir("tenant-1", "v1")
            PosixPath('ui_packs/tenant-1/v1')
        """

        tenant = _sanitize_segment("tenant_id", tenant_id)
        ver = _sanitize_segment("version", version)
        return self.root / tenant / ver

    def load_descriptor(self, tenant_id: str, version: str) -> UIPackDescriptor:
        """Load and validate the pack descriptor.

        Example:
            >>> storage = UIPackStorage("ui_packs")
            >>> storage.load_descriptor("tenant-1", "v1")  # doctest: +SKIP
            UIPackDescriptor(...)
        """

        pack_dir = self.resolve_pack_dir(tenant_id, version)
        descriptor_path = pack_dir / "pack.json"
        if not descriptor_path.exists():
            raise UIPackError(f"Missing pack descriptor: {descriptor_path}")

        try:
            raw = json.loads(descriptor_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise UIPackError(f"Invalid pack.json: {exc}") from exc

        _verify_signature(raw)

        schema_version = int(raw.get("schema_version", PACK_SCHEMA_VERSION))
        if schema_version != PACK_SCHEMA_VERSION:
            raise UIPackError(
                f"Unsupported pack schema {schema_version}; expected {PACK_SCHEMA_VERSION}."
            )

        entrypoint = str(raw.get("entrypoint", "")).strip()
        if not entrypoint:
            raise UIPackError("pack.json missing entrypoint.")

        manifest = raw.get("manifest")
        if not isinstance(manifest, dict):
            raise UIPackError("pack.json manifest must be an object.")

        assets = raw.get("assets")
        if not isinstance(assets, dict):
            raise UIPackError("pack.json assets must be an object.")

        metadata = raw.get("metadata")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise UIPackError("pack.json metadata must be an object.")

        return UIPackDescriptor(
            tenant_id=_sanitize_segment("tenant_id", tenant_id),
            version=_sanitize_segment("version", version),
            entrypoint=entrypoint,
            manifest=manifest,
            assets=assets,
            metadata=metadata,
            schema_version=schema_version,
            pack_root=pack_dir,
        )

    def verify_assets(self, descriptor: UIPackDescriptor) -> list[str]:
        """Verify SHA-256 integrity for pack assets.

        Example:
            >>> storage = UIPackStorage("ui_packs")
            >>> desc = storage.load_descriptor("tenant-1", "v1")  # doctest: +SKIP
            >>> storage.verify_assets(desc)  # doctest: +SKIP
            []
        """

        failures: list[str] = []
        for asset_path, info in descriptor.assets.items():
            expected = str(info.get("sha256", "")).strip().lower()
            if not expected:
                failures.append(asset_path)
                continue
            resolved = self.resolve_asset_path(descriptor, asset_path)
            if not resolved.exists():
                failures.append(asset_path)
                continue
            actual = _sha256_file(resolved)
            if actual != expected:
                failures.append(asset_path)
        return failures

    def resolve_asset_path(self, descriptor: UIPackDescriptor, asset_path: str) -> Path:
        """Resolve and validate asset path within a pack directory.

        Example:
            >>> storage = UIPackStorage("ui_packs")
            >>> desc = UIPackDescriptor("t","v","index.js",{}, {}, pack_root=Path("ui_packs/t/v"))
            >>> storage.resolve_asset_path(desc, "index.js")
            PosixPath('ui_packs/t/v/index.js')
        """

        cleaned = str(asset_path or "").strip().lstrip("/")
        if not cleaned:
            raise UIPackError("Empty asset path.")
        candidate = (descriptor.pack_root / cleaned).resolve()
        if not _is_relative_to(candidate, descriptor.pack_root.resolve()):
            raise UIPackError("Asset path traversal detected.")
        return candidate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sanitize_segment(label: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise UIPackError(f"{label} is required.")
    if not _SEGMENT_RE.match(cleaned):
        raise UIPackError(f"{label} has invalid characters.")
    return cleaned


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _verify_signature(raw: dict[str, Any]) -> None:
    key = str(os.getenv("ARCHON_UI_PACK_SIGNING_KEY", "")).strip()
    if not key:
        return
    signature = str(raw.get("signature", "")).strip()
    if not signature:
        raise UIPackError("pack.json missing signature.")
    payload = {
        key: raw[key]
        for key in ("schema_version", "entrypoint", "manifest", "assets", "metadata", "version")
        if key in raw
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected = hmac.new(key.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise UIPackError("Invalid pack signature.")
