"""GUI action execution with approval gating and screenshot logging."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from archon.core.approval_gate import ApprovalGate
from archon.vision.screen_capture import ScreenCapture, ScreenFrame
from archon.vision.ui_parser import UILayout

try:  # pragma: no cover - optional dependency
    import pyautogui as _pyautogui  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency
    _pyautogui = None


@dataclass(slots=True)
class ActionLogEntry:
    """One GUI action audit row with before/after screenshots."""

    action: str
    context: dict[str, Any]
    before_frame: ScreenFrame
    after_frame: ScreenFrame
    timestamp: float
    success: bool
    error: str | None = None


class ActionAgent:
    """Executes UI actions with optional approval gate checks."""

    def __init__(
        self,
        approval_gate: ApprovalGate,
        *,
        screen_capture: ScreenCapture | None = None,
        pyautogui_module: Any | None = None,
    ) -> None:
        self.approval_gate = approval_gate
        self.screen_capture = screen_capture or ScreenCapture()
        self._pyautogui = pyautogui_module if pyautogui_module is not None else _pyautogui
        self._action_log: list[ActionLogEntry] = []

    async def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> None:
        """Click at screen coordinates.

        Example:
            >>> await action_agent.click(120, 240, button="left")
        """

        pyautogui = self._require_pyautogui()
        await self._perform(
            action="click",
            context={"x": x, "y": y, "button": button},
            requires_gate=True,
            event_sink=event_sink,
            timeout_seconds=timeout_seconds,
            operation=lambda: pyautogui.click(x=x, y=y, button=button),
        )

    async def type_text(self, text: str, interval_ms: int = 50) -> None:
        """Type text without approval gate.

        Example:
            >>> await action_agent.type_text("hello", interval_ms=40)
        """

        pyautogui = self._require_pyautogui()
        interval_seconds = max(0, int(interval_ms)) / 1000
        await self._perform(
            action="type_text",
            context={"text_length": len(text), "interval_ms": int(interval_ms)},
            requires_gate=False,
            operation=lambda: pyautogui.write(text, interval=interval_seconds),
        )

    async def hotkey(
        self,
        *keys: str,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> None:
        """Press a keyboard shortcut.

        Example:
            >>> await action_agent.hotkey("ctrl", "c")
        """

        if not keys:
            raise ValueError("hotkey requires at least one key.")
        pyautogui = self._require_pyautogui()
        await self._perform(
            action="hotkey",
            context={"keys": list(keys)},
            requires_gate=True,
            event_sink=event_sink,
            timeout_seconds=timeout_seconds,
            operation=lambda: pyautogui.hotkey(*keys),
        )

    async def scroll(self, x: int, y: int, clicks: int) -> None:
        """Scroll at coordinates without approval gate.

        Example:
            >>> await action_agent.scroll(800, 500, -3)
        """

        pyautogui = self._require_pyautogui()

        def _scroll() -> None:
            pyautogui.moveTo(x, y)
            pyautogui.scroll(clicks)

        await self._perform(
            action="scroll",
            context={"x": x, "y": y, "clicks": clicks},
            requires_gate=False,
            operation=_scroll,
        )

    async def drag(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> None:
        """Drag from one coordinate to another.

        Example:
            >>> await action_agent.drag(100, 100, 300, 300)
        """

        pyautogui = self._require_pyautogui()

        def _drag() -> None:
            pyautogui.moveTo(x1, y1)
            pyautogui.dragTo(x2, y2, duration=0.2, button="left")

        await self._perform(
            action="drag",
            context={"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            requires_gate=True,
            event_sink=event_sink,
            timeout_seconds=timeout_seconds,
            operation=_drag,
        )

    async def find_and_click(
        self,
        element_id: str,
        layout: UILayout,
        *,
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> None:
        """Resolve an element center from layout and click it.

        Example:
            >>> await action_agent.find_and_click("submit-btn", layout)
        """

        target = next((element for element in layout.elements if element.element_id == element_id), None)
        if target is None:
            raise ValueError(f"Element id not found in layout: {element_id}")

        pyautogui = self._require_pyautogui()
        center_x = target.bounds.x + max(1, target.bounds.width) // 2
        center_y = target.bounds.y + max(1, target.bounds.height) // 2
        await self._perform(
            action="find_and_click",
            context={"element_id": element_id, "x": center_x, "y": center_y},
            requires_gate=True,
            event_sink=event_sink,
            timeout_seconds=timeout_seconds,
            operation=lambda: pyautogui.click(x=center_x, y=center_y, button="left"),
        )

    def get_action_log(self) -> list[ActionLogEntry]:
        """Return a copy of the action log.

        Example:
            >>> entries = action_agent.get_action_log()
            >>> isinstance(entries, list)
            True
        """

        return list(self._action_log)

    async def _perform(
        self,
        *,
        action: str,
        context: dict[str, Any],
        requires_gate: bool,
        operation: Callable[[], None],
        event_sink=None,
        timeout_seconds: float | None = None,
    ) -> None:
        before_frame = self.screen_capture.capture()
        after_frame = before_frame
        success = False
        error: str | None = None

        try:
            if requires_gate:
                gate_context = dict(context)
                if callable(event_sink):
                    gate_context["event_sink"] = event_sink
                if timeout_seconds is not None:
                    gate_context["timeout_seconds"] = timeout_seconds
                action_id = f"gui-{uuid.uuid4().hex[:12]}"
                await self.approval_gate.check(
                    action="gui_form_submit",
                    context=gate_context,
                    action_id=action_id,
                )
            operation()
            success = True
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            try:
                after_frame = self.screen_capture.capture()
            except Exception:
                after_frame = before_frame
            self._action_log.append(
                ActionLogEntry(
                    action=action,
                    context=dict(context),
                    before_frame=before_frame,
                    after_frame=after_frame,
                    timestamp=time.time(),
                    success=success,
                    error=error,
                )
            )

    def _require_pyautogui(self):
        if self._pyautogui is None:
            raise RuntimeError("pyautogui is required for ActionAgent operations.")
        return self._pyautogui
