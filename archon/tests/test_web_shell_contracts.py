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


def test_dashboard_shell_wires_live_mission_control_and_studio() -> None:
    source = (
        _REPO_ROOT / "archon" / "interfaces" / "web" / "dashboard" / "src" / "App.jsx"
    ).read_text(encoding="utf-8")

    assert "window.useARCHONContext" in source
    assert "fetch(`${apiBase}/studio/workflows`" in source
    assert "fetch(`${apiBase}/studio/run`" in source
    assert "new WebSocket(url)" in source
    assert "Agent Canvas" in source
    assert "Approvals" in source
    assert "Live Feed" in source
    assert "Run Now" in source
