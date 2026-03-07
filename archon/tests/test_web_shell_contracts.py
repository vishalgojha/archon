"""Contract tests for Studio and dashboard shell behavior."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_studio_shell_uses_executable_js_assets_and_token_gate() -> None:
    html = (_REPO_ROOT / "archon" / "interfaces" / "web" / "studio" / "index.html").read_text(
        encoding="utf-8"
    )
    js = (_REPO_ROOT / "archon" / "interfaces" / "web" / "studio" / "index.js").read_text(
        encoding="utf-8"
    )
    canvas_js = (
        _REPO_ROOT / "archon" / "interfaces" / "web" / "studio" / "WorkflowCanvas.js"
    ).read_text(encoding="utf-8")

    assert "/studio/assets/WorkflowCanvas.js" in html
    assert "/studio/assets/NodeEditor.js" in html
    assert "/studio/assets/WorkflowCanvas.jsx" not in html
    assert "/studio/assets/NodeEditor.jsx" not in html
    assert "function TokenGate" in js
    assert "studioApiFetch" in js
    assert "Authorization" in js
    assert "Blueprint a workflow before wiring the details" in canvas_js
    assert "Run Timeline" in js


def test_dashboard_defaults_to_civilian_and_keeps_friendlier_copy() -> None:
    source = (
        _REPO_ROOT / "archon" / "interfaces" / "web" / "dashboard" / "src" / "App.jsx"
    ).read_text(encoding="utf-8")

    assert 'safeStorageGet("archon.dashboard.mode") || "civilian"' in source
    assert "Operations Overview" in source
    assert "What Needs Attention" in source
    assert "Latest Answer" in source
