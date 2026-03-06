"""Tests for vision capture, UI parsing, action execution, recovery, and audit trail."""

from __future__ import annotations

import json
import shutil
import types
from pathlib import Path

import pytest

from archon.vision.action_agent import ActionAgent
from archon.vision.audit_agent import AuditAgent
from archon.vision.error_recovery import ErrorRecovery
from archon.vision.screen_capture import ScreenCapture, ScreenFrame
from archon.vision.ui_parser import Bounds, UIElement, UILayout, UIParser


class _FakeShot:
    def __init__(self, width: int, height: int) -> None:
        self.size = (width, height)
        self.rgb = b"\x00" * max(1, width * height * 3)
        self.png = f"png-{width}x{height}".encode("ascii")


class _FakeMSSSession:
    def __init__(self, monitors: list[dict[str, int]]) -> None:
        self.monitors = monitors

    def __enter__(self) -> "_FakeMSSSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        del exc_type, exc, tb

    def grab(self, monitor: dict[str, int]) -> _FakeShot:
        return _FakeShot(monitor["width"], monitor["height"])


def test_screen_capture_mss_capture_list_and_region(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.vision.screen_capture as screen_capture_module

    monitors = [
        {"left": 0, "top": 0, "width": 200, "height": 100},
        {"left": 0, "top": 0, "width": 120, "height": 80},
        {"left": 120, "top": 0, "width": 80, "height": 80},
    ]
    fake_mss = types.SimpleNamespace(mss=lambda: _FakeMSSSession(monitors))
    monkeypatch.setattr(screen_capture_module, "mss", fake_mss)

    capture = ScreenCapture()
    displays = capture.list_displays()
    assert len(displays) == 2
    assert displays[0].id == 0
    assert displays[0].is_primary is True
    assert displays[1].width == 80

    frame = capture.capture()
    assert isinstance(frame, ScreenFrame)
    assert frame.width == 120
    assert frame.height == 80
    assert frame.display_id == 0
    assert frame.image_bytes.startswith(b"png-")

    region = capture.capture_region(5, 7, 20, 30)
    assert region.width == 20
    assert region.height == 30
    assert region.image_bytes.startswith(b"png-")


class _FakeRouter:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.calls = 0
        self.prompts: list[str] = []

    async def invoke(self, *, role: str, prompt: str):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.prompts.append(prompt)
        return types.SimpleNamespace(text=self.response_text, provider="fake", model=f"{role}-model")


@pytest.mark.asyncio
async def test_ui_parser_parses_layout_and_uses_cache() -> None:
    payload = json.dumps(
        [
            {
                "type": "button",
                "text": "Submit",
                "bounds": {"x": 10, "y": 20, "width": 80, "height": 24},
                "confidence": 0.97,
                "element_id": "submit-btn",
            }
        ]
    )
    router = _FakeRouter(payload)
    parser = UIParser(router)
    frame = ScreenFrame(
        image_bytes=b"fake-image-bytes",
        width=200,
        height=120,
        timestamp=1.0,
        display_id=0,
    )

    layout = await parser.parse(frame)
    assert len(layout.elements) == 1
    element = layout.elements[0]
    assert element.type == "button"
    assert element.text == "Submit"
    assert element.bounds == Bounds(x=10, y=20, width=80, height=24)
    assert element.element_id == "submit-btn"

    cached_layout = await parser.parse(frame)
    assert cached_layout is layout
    assert router.calls == 1


@pytest.mark.asyncio
async def test_ui_parser_handles_malformed_json_gracefully() -> None:
    router = _FakeRouter("not-json-at-all")
    parser = UIParser(router)
    frame = ScreenFrame(
        image_bytes=b"another-image",
        width=100,
        height=60,
        timestamp=1.0,
        display_id=0,
    )

    layout = await parser.parse(frame)
    assert layout.elements == []
    assert layout.parse_error == "malformed_json"
    assert router.calls == 1


class _FakeGate:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def check(self, action: str, context: dict[str, object], action_id: str) -> str:
        self.calls.append({"action": action, "context": context, "action_id": action_id})
        return action_id


class _FakePyAutoGUI:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def click(self, *, x: int, y: int, button: str = "left") -> None:
        self.calls.append(("click", x, y, button))

    def write(self, text: str, *, interval: float = 0.0) -> None:
        self.calls.append(("write", text, interval))

    def hotkey(self, *keys: str) -> None:
        self.calls.append(("hotkey", keys))

    def moveTo(self, x: int, y: int) -> None:  # noqa: N802
        self.calls.append(("moveTo", x, y))

    def scroll(self, clicks: int) -> None:
        self.calls.append(("scroll", clicks))

    def dragTo(self, x: int, y: int, *, duration: float = 0.0, button: str = "left") -> None:  # noqa: N802
        self.calls.append(("dragTo", x, y, duration, button))


class _FakeCapture:
    def __init__(self) -> None:
        self.counter = 0

    def capture(self) -> ScreenFrame:
        self.counter += 1
        return ScreenFrame(
            image_bytes=f"frame-{self.counter}".encode("ascii"),
            width=100,
            height=60,
            timestamp=float(self.counter),
            display_id=0,
        )


@pytest.mark.asyncio
async def test_action_agent_click_type_hotkey_and_gate_behavior() -> None:
    gate = _FakeGate()
    pyautogui = _FakePyAutoGUI()
    capture = _FakeCapture()
    agent = ActionAgent(gate, screen_capture=capture, pyautogui_module=pyautogui)

    await agent.click(10, 20, button="right")
    await agent.type_text("hello", interval_ms=40)
    await agent.hotkey("ctrl", "c")

    assert ("click", 10, 20, "right") in pyautogui.calls
    write_calls = [row for row in pyautogui.calls if row[0] == "write"]
    assert write_calls
    assert write_calls[0][1] == "hello"
    assert write_calls[0][2] == pytest.approx(0.04, abs=1e-6)
    assert ("hotkey", ("ctrl", "c")) in pyautogui.calls

    gated_actions = [call["action"] for call in gate.calls]
    assert gated_actions == ["gui_form_submit", "gui_form_submit"]


@pytest.mark.asyncio
async def test_action_agent_non_gated_scroll_and_type() -> None:
    gate = _FakeGate()
    pyautogui = _FakePyAutoGUI()
    capture = _FakeCapture()
    agent = ActionAgent(gate, screen_capture=capture, pyautogui_module=pyautogui)

    await agent.scroll(5, 6, -2)
    await agent.type_text("x")

    assert ("moveTo", 5, 6) in pyautogui.calls
    assert ("scroll", -2) in pyautogui.calls
    assert len(gate.calls) == 0


class _FakeParser:
    def __init__(self, layout: UILayout) -> None:
        self.layout = layout
        self.calls = 0

    async def parse(self, frame: ScreenFrame) -> UILayout:
        del frame
        self.calls += 1
        return self.layout


@pytest.mark.asyncio
async def test_error_recovery_detect_popup_and_retry() -> None:
    gate = _FakeGate()
    pyautogui = _FakePyAutoGUI()
    capture = _FakeCapture()
    action_agent = ActionAgent(gate, screen_capture=capture, pyautogui_module=pyautogui)
    layout = UILayout(
        elements=[
            UIElement(
                type="text",
                text="Error: form submission failed",
                bounds=Bounds(0, 0, 100, 30),
                confidence=0.9,
                element_id="msg-1",
            ),
            UIElement(
                type="button",
                text="OK",
                bounds=Bounds(10, 40, 40, 20),
                confidence=0.95,
                element_id="ok-btn",
            ),
        ]
    )
    parser = _FakeParser(layout)
    recovery = ErrorRecovery(action_agent, parser)

    popup = recovery.detect_popup(layout)
    assert popup is not None
    assert popup.type == "error"
    assert "OK" in popup.buttons

    attempts = {"count": 0}

    async def flaky_operation() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient failure")
        return "success"

    result = await recovery.retry_with_recovery(flaky_operation, max_retries=3)
    assert result == "success"
    assert attempts["count"] == 3
    assert parser.calls == 2
    click_calls = [row for row in pyautogui.calls if row[0] == "click"]
    assert len(click_calls) >= 2


def test_audit_agent_records_and_exports() -> None:
    capture = _FakeCapture()
    audit = AuditAgent(screen_capture=capture)

    with audit.record("click", {"x": 10, "y": 20}):
        pass

    with pytest.raises(RuntimeError):
        with audit.record("submit", {"form": "lead"}):
            raise RuntimeError("forced failure")

    trail = audit.get_audit_trail()
    assert len(trail) == 2
    assert trail[0].success is True
    assert trail[1].success is False
    assert trail[1].error and "forced failure" in trail[1].error

    temp_root = Path("archon/tests/_tmp_audit_out")
    shutil.rmtree(temp_root, ignore_errors=True)
    try:
        output_dir = temp_root / "audit"
        manifest_path = audit.export_audit(output_dir)
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["entry_count"] == 2

        png_files = list(output_dir.glob("*.png"))
        assert len(png_files) == 4
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
