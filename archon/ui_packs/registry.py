"""SQLite-backed UI pack registry."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archon.ui_packs.storage import UIPackDescriptor


def _now() -> float:
    return time.time()


@dataclass(slots=True)
class UIPackMetadata:
    """Serialized UI pack metadata."""

    tenant_id: str
    version: str
    entrypoint: str
    manifest: dict[str, Any]
    assets: dict[str, Any]
    created_at: float
    created_by: str
    schema_version: int
    digest: str
    metadata: dict[str, Any] = field(default_factory=dict)


class UIPackRegistry:
    """SQLite-backed UI pack registry.

    Example:
        >>> registry = UIPackRegistry(path=":memory:")
        >>> isinstance(registry.list_versions("tenant-1"), list)
        True
    """

    def __init__(self, path: str | Path = "archon_ui_packs.sqlite3") -> None:
        """Create registry storage.

        Example:
            >>> UIPackRegistry(path=":memory:").path.as_posix()
            ':memory:'
        """

        self.path = Path(path)
        self._init_db()

    def register_pack(
        self,
        *,
        descriptor: UIPackDescriptor,
        created_by: str | None = None,
    ) -> UIPackMetadata:
        """Register a UI pack version and return stored metadata.

        Example:
            >>> # registry.register_pack(descriptor=desc)  # doctest: +SKIP
            >>> True
            True
        """

        created_by_clean = str(created_by or "system").strip() or "system"
        metadata = UIPackMetadata(
            tenant_id=descriptor.tenant_id,
            version=descriptor.version,
            entrypoint=descriptor.entrypoint,
            manifest=descriptor.manifest,
            assets=descriptor.assets,
            created_at=_now(),
            created_by=created_by_clean,
            schema_version=descriptor.schema_version,
            digest=_pack_digest(descriptor),
            metadata=descriptor.metadata,
        )

        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO ui_packs(
                        tenant_id,
                        version,
                        entrypoint,
                        manifest_json,
                        assets_json,
                        metadata_json,
                        schema_version,
                        digest,
                        created_at,
                        created_by
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        metadata.tenant_id,
                        metadata.version,
                        metadata.entrypoint,
                        json.dumps(metadata.manifest),
                        json.dumps(metadata.assets),
                        json.dumps(metadata.metadata),
                        metadata.schema_version,
                        metadata.digest,
                        metadata.created_at,
                        metadata.created_by,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"UI pack {metadata.tenant_id}:{metadata.version} already exists."
                ) from exc

        return metadata

    def get_pack(self, tenant_id: str, version: str) -> UIPackMetadata | None:
        """Fetch a pack metadata record by tenant and version.

        Example:
            >>> registry = UIPackRegistry(path=":memory:")
            >>> registry.get_pack("tenant-1", "v1") is None
            True
        """

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT tenant_id,
                       version,
                       entrypoint,
                       manifest_json,
                       assets_json,
                       metadata_json,
                       schema_version,
                       digest,
                       created_at,
                       created_by
                FROM ui_packs
                WHERE tenant_id = ? AND version = ?
                """,
                (str(tenant_id or "").strip(), str(version or "").strip()),
            ).fetchone()
        return _to_metadata(row)

    def list_versions(self, tenant_id: str) -> list[str]:
        """List available versions for one tenant.

        Example:
            >>> registry = UIPackRegistry(path=":memory:")
            >>> registry.list_versions("tenant-1")
            []
        """

        tenant_clean = str(tenant_id or "").strip()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT version FROM ui_packs WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_clean,),
            ).fetchall()
        return [str(row["version"]) for row in rows]

    def set_active_version(
        self, *, tenant_id: str, version: str, updated_by: str | None = None
    ) -> UIPackMetadata:
        """Set active UI pack version for a tenant.

        Example:
            >>> # registry.set_active_version(tenant_id="t", version="v1")  # doctest: +SKIP
            >>> True
            True
        """

        tenant_clean = str(tenant_id or "").strip()
        version_clean = str(version or "").strip()
        target = self.get_pack(tenant_clean, version_clean)
        if target is None:
            raise KeyError(f"UI pack {tenant_clean}:{version_clean} not found.")

        updated_by_clean = str(updated_by or "system").strip() or "system"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ui_pack_active(tenant_id, version, updated_at, updated_by)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    version = excluded.version,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (tenant_clean, version_clean, _now(), updated_by_clean),
            )
        return target

    def get_active_pack(self, tenant_id: str) -> UIPackMetadata | None:
        """Fetch active UI pack metadata for a tenant.

        Example:
            >>> registry = UIPackRegistry(path=":memory:")
            >>> registry.get_active_pack("tenant-1") is None
            True
        """

        tenant_clean = str(tenant_id or "").strip()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT p.tenant_id,
                       p.version,
                       p.entrypoint,
                       p.manifest_json,
                       p.assets_json,
                       p.metadata_json,
                       p.schema_version,
                       p.digest,
                       p.created_at,
                       p.created_by
                FROM ui_pack_active a
                JOIN ui_packs p
                  ON p.tenant_id = a.tenant_id AND p.version = a.version
                WHERE a.tenant_id = ?
                """,
                (tenant_clean,),
            ).fetchone()
        return _to_metadata(row)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ui_packs (
                    tenant_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    entrypoint TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    assets_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    digest TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    created_by TEXT NOT NULL,
                    PRIMARY KEY(tenant_id, version)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ui_pack_active (
                    tenant_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    updated_by TEXT NOT NULL
                )
                """
            )


def _to_metadata(row: sqlite3.Row | None) -> UIPackMetadata | None:
    if row is None:
        return None
    return UIPackMetadata(
        tenant_id=str(row["tenant_id"]),
        version=str(row["version"]),
        entrypoint=str(row["entrypoint"]),
        manifest=json.loads(row["manifest_json"]),
        assets=json.loads(row["assets_json"]),
        metadata=json.loads(row["metadata_json"]),
        schema_version=int(row["schema_version"]),
        digest=str(row["digest"]),
        created_at=float(row["created_at"]),
        created_by=str(row["created_by"]),
    )


def _pack_digest(descriptor: UIPackDescriptor) -> str:
    payload = {
        "tenant_id": descriptor.tenant_id,
        "version": descriptor.version,
        "entrypoint": descriptor.entrypoint,
        "schema_version": descriptor.schema_version,
        "manifest": descriptor.manifest,
        "assets": descriptor.assets,
        "metadata": descriptor.metadata,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return _sha256_text(encoded)


def _sha256_text(text: str) -> str:
    return __import__("hashlib").sha256(text.encode("utf-8")).hexdigest()
