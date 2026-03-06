"""Error recovery helpers for GUI automation flows."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Literal

from archon.vision.action_agent import ActionAgent
from archon.vision.ui_parser import UILayout

PopupType = Literal["alert", "confirm", "error", "dialog", "captcha"]


@dataclass(slots=True, frozen=True)
class PopupInfo:
    """Detected popup metadata."""

    type: PopupType
    message: str
    buttons: list[str]


class UnexpectedUIStateError(RuntimeError):
    """Raised when expected elements are missing from a parsed layout."""


class ErrorRecovery:
    """Retries actions and handles popup interruptions."""

    def __init__(
        self,
        action_agent: ActionAgent,
        ui_parser: Any,
        *,
        expected_elements: list[str] | None = None,
    ) -> None:
        self.action_agent = action_agent
        self.ui_parser = ui_parser
        self.expected_elements = list(expected_elements or [])
        self._last_layout: UILayout | None = None

    def detect_popup(self, layout: UILayout) -> PopupInfo | None:
        """Detect common popup states from parsed layout.

        Example:
            >>> popup = recovery.detect_popup(layout)
            >>> popup is None or popup.type in {"alert", "confirm", "error", "dialog", "captcha"}
            True
        """

        self._last_layout = layout
        texts = [element.text.strip() for element in layout.elements if element.text.strip()]
        buttons = [
            element.text.strip()
            for element in layout.elements
            if element.type == "button" and element.text.strip()
        ]
        if not texts and not buttons:
            return None

        merged = " ".join(texts).lower()
        if "captcha" in merged or "not a robot" in merged:
            return PopupInfo(type="captcha", message=_popup_message(texts), buttons=buttons)
        if any(token in merged for token in ("error", "failed", "invalid", "unable")):
            return PopupInfo(type="error", message=_popup_message(texts), buttons=buttons)
        if _has_button(buttons, ("yes", "no", "confirm", "cancel", "ok")):
            return PopupInfo(type="confirm", message=_popup_message(texts), buttons=buttons)
        if any(token in merged for token in ("alert", "warning", "notice")):
            return PopupInfo(type="alert", message=_popup_message(texts), buttons=buttons)
        if _has_button(buttons, ("close", "dismiss", "ok", "cancel")):
            return PopupInfo(type="dialog", message=_popup_message(texts), buttons=buttons)
        return None

    async def handle_popup(self, popup: PopupInfo, strategy: str = "dismiss") -> bool:
        """Attempt to resolve popup by clicking a matching button.

        Example:
            >>> handled = await recovery.handle_popup(popup, strategy="dismiss")
            >>> isinstance(handled, bool)
            True
        """

        layout = self._last_layout
        if layout is None:
            raise RuntimeError("No layout available for popup handling.")

        button_text = _select_button_text(popup.buttons, strategy)
        if button_text is None:
            return False

        target = next(
            (
                element
                for element in layout.elements
                if element.type == "button" and element.text.strip().lower() == button_text.lower()
            ),
            None,
        )
        if target is None:
            return False

        await self.action_agent.find_and_click(target.element_id, layout)
        return True

    async def retry_with_recovery(self, fn: Callable[[], Any], max_retries: int = 3) -> Any:
        """Retry an operation with popup-aware recovery.

        Example:
            >>> result = await recovery.retry_with_recovery(operation, max_retries=3)
        """

        if max_retries < 1:
            raise ValueError("max_retries must be at least 1.")

        attempt = 0
        while True:
            try:
                result = fn()
                if inspect.isawaitable(result):
                    return await result
                return result
            except Exception:
                attempt += 1
                if attempt >= max_retries:
                    raise

                frame = self.action_agent.screen_capture.capture()
                layout = await self.ui_parser.parse(frame)
                popup = self.detect_popup(layout)
                if popup is not None:
                    await self.handle_popup(popup, strategy="dismiss")

    def on_unexpected_state(self, layout: UILayout) -> None:
        """Validate that expected element IDs are present.

        Example:
            >>> recovery.on_unexpected_state(layout)
        """

        if not self.expected_elements:
            return

        available = {element.element_id for element in layout.elements}
        missing = [
            element_id for element_id in self.expected_elements if element_id not in available
        ]
        if missing:
            raise UnexpectedUIStateError(
                f"Unexpected UI state. Missing expected elements: {missing}"
            )


def _popup_message(texts: list[str]) -> str:
    return texts[0] if texts else ""


def _has_button(buttons: list[str], needles: tuple[str, ...]) -> bool:
    lowered = [button.lower() for button in buttons]
    return any(any(needle in button for needle in needles) for button in lowered)


def _select_button_text(buttons: list[str], strategy: str) -> str | None:
    if not buttons:
        return None

    preference_map: dict[str, tuple[str, ...]] = {
        "dismiss": ("dismiss", "close", "cancel", "no", "ok"),
        "confirm": ("yes", "confirm", "continue", "submit", "ok"),
        "retry": ("retry", "try again", "ok"),
    }
    preferences = preference_map.get(strategy.lower(), ())
    lowered = [(button, button.lower()) for button in buttons]
    for needle in preferences:
        match = next((original for original, lower in lowered if needle in lower), None)
        if match is not None:
            return match
    return buttons[0]
