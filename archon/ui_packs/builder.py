"""UI pack builder utilities for non-technical flows."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from archon.ui_packs.storage import UIPackStorage


@dataclass(slots=True)
class UIPackBuildResult:
    """Result of building a UI pack.

    Example:
        >>> result = UIPackBuildResult(pack_dir=Path("ui_packs/t/v1"), assets={})
        >>> result.pack_dir.name
        'v1'
    """

    pack_dir: Path
    assets: dict[str, dict[str, Any]]


def build_pack(
    *,
    tenant_id: str,
    version: str,
    blueprint: dict[str, Any],
    storage: UIPackStorage,
    created_by: str,
) -> UIPackBuildResult:
    """Build a UI pack from a blueprint and return the pack directory.

    Example:
        >>> storage = UIPackStorage(root="ui_packs")
        >>> build_pack(tenant_id="t", version="v1", blueprint={}, storage=storage, created_by="t")
        UIPackBuildResult(pack_dir=PosixPath('ui_packs/t/v1'), assets=...)
    """

    pack_dir = storage.resolve_pack_dir(tenant_id, version)
    pack_dir.mkdir(parents=True, exist_ok=True)

    normalized = _normalize_blueprint(blueprint)
    styles_css = _render_styles_css(normalized)
    index_js = _render_pack_js()
    styles_bytes = styles_css.encode("utf-8")
    index_bytes = index_js.encode("utf-8")

    assets = {
        "index.js": {
            "sha256": _sha256_bytes(index_bytes),
            "content_type": "text/javascript",
        },
        "styles.css": {
            "sha256": _sha256_bytes(styles_bytes),
            "content_type": "text/css",
        },
    }

    (pack_dir / "index.js").write_bytes(index_bytes)
    (pack_dir / "styles.css").write_bytes(styles_bytes)

    pack_json = {
        "schema_version": 1,
        "version": str(version),
        "entrypoint": "index.js",
        "manifest": normalized,
        "assets": assets,
        "metadata": {
            "created_at": time.time(),
            "created_by": created_by,
        },
    }
    _apply_signature(pack_json)
    (pack_dir / "pack.json").write_text(
        json.dumps(pack_json, indent=2, sort_keys=True), encoding="utf-8"
    )

    return UIPackBuildResult(pack_dir=pack_dir, assets=assets)


def _normalize_blueprint(blueprint: dict[str, Any]) -> dict[str, Any]:
    title = str(blueprint.get("title") or "Custom Workspace").strip() or "Custom Workspace"
    summary = str(blueprint.get("summary") or "Self-evolving operator console.").strip()
    theme = blueprint.get("theme") if isinstance(blueprint.get("theme"), dict) else {}
    draw = blueprint.get("drawers")
    drawers: list[dict[str, Any]] = []
    if isinstance(draw, list):
        for idx, raw in enumerate(draw):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("title") or f"Drawer {idx + 1}").strip()
            drawers.append(
                {
                    "id": _slugify(str(raw.get("id") or name or f"drawer-{idx+1}")),
                    "title": name,
                    "type": str(raw.get("type") or "list").strip(),
                    "description": str(raw.get("description") or "").strip(),
                    "items": raw.get("items") if isinstance(raw.get("items"), list) else [],
                    "columns": raw.get("columns") if isinstance(raw.get("columns"), list) else [],
                }
            )
    if not drawers:
        drawers = [
            {
                "id": "overview",
                "title": "Overview",
                "type": "summary",
                "description": "Describe your workflow and desired outcomes.",
                "items": [],
                "columns": [],
            }
        ]

    return {
        "title": title,
        "summary": summary,
        "theme": {
            "accent": str(theme.get("accent") or "#ff6b35").strip(),
            "accentSoft": str(theme.get("accentSoft") or "#f7b267").strip(),
            "bg": str(theme.get("bg") or "#0f1115").strip(),
            "panel": str(theme.get("panel") or "#171c2b").strip(),
            "text": str(theme.get("text") or "#f8fafc").strip(),
            "muted": str(theme.get("muted") or "#9aa3b2").strip(),
            "font": str(theme.get("font") or "Sora").strip(),
        },
        "drawers": drawers,
    }


def _render_styles_css(blueprint: dict[str, Any]) -> str:
    theme = blueprint.get("theme") if isinstance(blueprint.get("theme"), dict) else {}
    return f"""
.archon-pack-root {{
  --pack-bg: {theme.get("bg", "#0f1115")};
  --pack-panel: {theme.get("panel", "#171c2b")};
  --pack-text: {theme.get("text", "#f8fafc")};
  --pack-muted: {theme.get("muted", "#9aa3b2")};
  --pack-accent: {theme.get("accent", "#ff6b35")};
  --pack-accent-soft: {theme.get("accentSoft", "#f7b267")};
  font-family: {theme.get("font", "Sora")}, system-ui, -apple-system, sans-serif;
  color: var(--pack-text);
}}

.archon-pack-grid {{
  display: grid;
  gap: 12px;
}}

.archon-pack-card {{
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  background: var(--pack-panel);
  padding: 12px;
}}

.archon-pack-card h3 {{
  margin: 0 0 6px 0;
  font-size: 14px;
}}

.archon-pack-card p {{
  margin: 0;
  font-size: 12px;
  color: var(--pack-muted);
}}

.archon-pack-pill {{
  display: inline-flex;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 11px;
  background: rgba(255, 255, 255, 0.08);
}}

.archon-pack-items {{
  margin-top: 8px;
  display: grid;
  gap: 6px;
}}

.archon-pack-item {{
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.06);
  font-size: 12px;
}}
""".strip()


def _render_pack_js() -> str:
    return """
(function () {
  const React = window.React;
  const ReactDOM = window.ReactDOM;
  if (!React || !ReactDOM) {
    console.error("ARCHON pack requires React + ReactDOM.");
    return;
  }

  const { createElement: h, useMemo } = React;

  function DrawerCard({ drawer }) {
    const items = Array.isArray(drawer.items) ? drawer.items : [];
    const hasItems = items.length > 0;
    return h(
      "div",
      { className: "archon-pack-card" },
      h("h3", null, drawer.title || "Drawer"),
      drawer.description ? h("p", null, drawer.description) : null,
      h(
        "div",
        { className: "archon-pack-pill" },
        String(drawer.type || "list").toUpperCase()
      ),
      h(
        "div",
        { className: "archon-pack-items" },
        hasItems
          ? items.map((item, idx) =>
              h(
                "div",
                { className: "archon-pack-item", key: idx },
                typeof item === "string" ? item : JSON.stringify(item)
              )
            )
          : h(
              "div",
              { className: "archon-pack-item" },
              "Awaiting live data from your tools."
            )
      )
    );
  }

  function PackApp({ pack }) {
    const manifest = pack && pack.manifest ? pack.manifest : {};
    const drawers = Array.isArray(manifest.drawers) ? manifest.drawers : [];
    const title = manifest.title || "Custom Workspace";
    const summary = manifest.summary || "Self-evolving operator console.";

    const gridStyle = useMemo(
      () => ({
        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
      }),
      []
    );

    return h(
      "div",
      { className: "archon-pack-root" },
      h("h2", null, title),
      h("p", null, summary),
      h(
        "div",
        { className: "archon-pack-grid", style: gridStyle },
        drawers.map((drawer) =>
          h(DrawerCard, { key: drawer.id || drawer.title, drawer })
        )
      )
    );
  }

  function mount({ root, bridge, pack }) {
    if (!root) {
      throw new Error("Pack mount requires a root element.");
    }
    const cssId = "archon-pack-style";
    if (!document.getElementById(cssId)) {
      const link = document.createElement("link");
      link.id = cssId;
      link.rel = "stylesheet";
      link.href = bridge.assetUrl("styles.css");
      document.head.appendChild(link);
    }

    const container = document.createElement("div");
    root.innerHTML = "";
    root.appendChild(container);
    const reactRoot = ReactDOM.createRoot(container);
    reactRoot.render(h(PackApp, { pack, bridge }));
    return () => reactRoot.unmount();
  }

  window.ARCHON_PACK = { mount };
})();
""".strip()


def _slugify(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value.lower())
    cleaned = "-".join(segment for segment in cleaned.split("-") if segment)
    return cleaned or "drawer"


def _sha256_text(text: str) -> str:
    return __import__("hashlib").sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return __import__("hashlib").sha256(value).hexdigest()


def _apply_signature(pack_json: dict[str, Any]) -> None:
    import os
    import hmac
    import hashlib

    key = str(os.getenv("ARCHON_UI_PACK_SIGNING_KEY", "")).strip()
    if not key:
        return
    payload = {
        k: pack_json[k]
        for k in ("schema_version", "entrypoint", "manifest", "assets", "metadata", "version")
        if k in pack_json
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(key.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).hexdigest()
    pack_json["signature"] = signature
