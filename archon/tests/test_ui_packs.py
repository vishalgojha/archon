from __future__ import annotations

from pathlib import Path

import pytest

from archon.ui_packs.builder import build_pack
from archon.ui_packs.registry import UIPackRegistry
from archon.ui_packs.storage import UIPackStorage


def test_build_pack_writes_assets(tmp_path: Path) -> None:
    storage = UIPackStorage(root=tmp_path / "ui_packs")
    result = build_pack(
        tenant_id="tenant-a",
        version="v1",
        blueprint={"title": "Demo", "drawers": [{"title": "Inbox", "type": "list"}]},
        storage=storage,
        created_by="tenant-a",
    )
    assert (result.pack_dir / "pack.json").exists()
    assert (result.pack_dir / "index.js").exists()
    assert (result.pack_dir / "styles.css").exists()
    assert "index.js" in result.assets


def test_registry_tracks_active_version(tmp_path: Path) -> None:
    storage = UIPackStorage(root=tmp_path / "ui_packs")
    build_pack(
        tenant_id="tenant-a",
        version="v1",
        blueprint={"title": "Demo"},
        storage=storage,
        created_by="tenant-a",
    )
    descriptor = storage.load_descriptor("tenant-a", "v1")
    registry = UIPackRegistry(path=tmp_path / "ui_packs.sqlite3")
    registry.register_pack(descriptor=descriptor, created_by="tenant-a")
    registry.set_active_version(tenant_id="tenant-a", version="v1", updated_by="tenant-a")
    active = registry.get_active_pack("tenant-a")
    assert active is not None
    assert active.version == "v1"


def test_storage_rejects_missing_descriptor(tmp_path: Path) -> None:
    storage = UIPackStorage(root=tmp_path / "ui_packs")
    with pytest.raises(Exception):
        storage.load_descriptor("tenant-a", "v1")
