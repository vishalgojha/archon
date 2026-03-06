"""Cross-platform screen capture utilities used by vision and GUI agents."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any

try:  # pragma: no cover - optional dependency
    import mss  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency
    mss = None

try:  # pragma: no cover - optional dependency
    from PIL import Image, ImageGrab  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency
    Image = None
    ImageGrab = None


@dataclass(slots=True, frozen=True)
class ScreenFrame:
    """Captured screen frame.

    Example:
        >>> frame = ScreenFrame(b"png", 1920, 1080, 1.0, 0)
        >>> frame.width
        1920
    """

    image_bytes: bytes
    width: int
    height: int
    timestamp: float
    display_id: int | None


@dataclass(slots=True, frozen=True)
class Display:
    """Display geometry descriptor.

    Example:
        >>> d = Display(0, 1920, 1080, 0, 0, True)
        >>> d.is_primary
        True
    """

    id: int
    width: int
    height: int
    x: int
    y: int
    is_primary: bool


class ScreenCapture:
    """Cross-platform screenshot capture with optional mss/PIL backends."""

    def __init__(self, *, all_screens: bool = True) -> None:
        self._all_screens = all_screens

    def capture(self) -> ScreenFrame:
        """Capture the primary display.

        Example:
            >>> frame = ScreenCapture().capture()
            >>> frame.width > 0
            True
        """

        displays = self.list_displays()
        if not displays:
            raise RuntimeError("No displays available for capture.")
        primary = next((display for display in displays if display.is_primary), displays[0])
        return self.capture_display(primary.id)

    def capture_region(self, x: int, y: int, w: int, h: int) -> ScreenFrame:
        """Capture a rectangular region.

        Example:
            >>> frame = ScreenCapture().capture_region(0, 0, 100, 100)
            >>> (frame.width, frame.height)
            (100, 100)
        """

        if w <= 0 or h <= 0:
            raise ValueError("capture_region requires positive width and height.")

        if mss is not None:
            monitor = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
            with mss.mss() as sct:
                shot = sct.grab(monitor)
            return ScreenFrame(
                image_bytes=_mss_frame_to_png(shot),
                width=int(w),
                height=int(h),
                timestamp=time.time(),
                display_id=None,
            )
        return self._capture_with_pil((int(x), int(y), int(x + w), int(y + h)), display_id=None)

    def capture_display(self, display_id: int) -> ScreenFrame:
        """Capture one monitor by ID.

        Example:
            >>> displays = ScreenCapture().list_displays()
            >>> frame = ScreenCapture().capture_display(displays[0].id)
        """

        if mss is not None:
            with mss.mss() as sct:
                physical = _physical_monitors(sct.monitors)
                if display_id < 0 or display_id >= len(physical):
                    raise ValueError(f"Unknown display id: {display_id}")
                monitor = physical[display_id]
                shot = sct.grab(monitor)
            return ScreenFrame(
                image_bytes=_mss_frame_to_png(shot),
                width=int(monitor["width"]),
                height=int(monitor["height"]),
                timestamp=time.time(),
                display_id=display_id,
            )

        if display_id != 0:
            raise ValueError("PIL fallback only supports display_id=0.")
        return self._capture_with_pil(None, display_id=0)

    def list_displays(self) -> list[Display]:
        """List available displays.

        Example:
            >>> displays = ScreenCapture().list_displays()
            >>> isinstance(displays, list)
            True
        """

        if mss is not None:
            with mss.mss() as sct:
                physical = _physical_monitors(sct.monitors)
            return [
                Display(
                    id=index,
                    width=int(monitor["width"]),
                    height=int(monitor["height"]),
                    x=int(monitor["left"]),
                    y=int(monitor["top"]),
                    is_primary=(index == 0),
                )
                for index, monitor in enumerate(physical)
            ]

        if ImageGrab is None:
            raise RuntimeError("No screen capture backend available (requires mss or Pillow).")

        image = _pil_grab(bbox=None, all_screens=self._all_screens)
        width, height = image.size
        return [Display(id=0, width=int(width), height=int(height), x=0, y=0, is_primary=True)]

    def _capture_with_pil(
        self, bbox: tuple[int, int, int, int] | None, display_id: int | None
    ) -> ScreenFrame:
        if ImageGrab is None:
            raise RuntimeError("Pillow ImageGrab not available for capture fallback.")
        image = _pil_grab(bbox=bbox, all_screens=self._all_screens)
        width, height = image.size
        output = io.BytesIO()
        image.save(output, format="PNG")
        return ScreenFrame(
            image_bytes=output.getvalue(),
            width=int(width),
            height=int(height),
            timestamp=time.time(),
            display_id=display_id,
        )


def _physical_monitors(monitors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(monitors) <= 1:
        return monitors
    return monitors[1:]


def _pil_grab(
    *, bbox: tuple[int, int, int, int] | None, all_screens: bool
):  # pragma: no cover - thin wrapper
    if ImageGrab is None:
        raise RuntimeError("Pillow ImageGrab not available.")
    try:
        return ImageGrab.grab(bbox=bbox, all_screens=all_screens)
    except TypeError:
        return ImageGrab.grab(bbox=bbox)


def _mss_frame_to_png(frame: Any) -> bytes:
    png = getattr(frame, "png", None)
    if isinstance(png, (bytes, bytearray)):
        return bytes(png)

    try:  # pragma: no cover - optional dependency branch
        import mss.tools  # type: ignore[import-untyped]

        converted = mss.tools.to_png(frame.rgb, frame.size)
        if isinstance(converted, (bytes, bytearray)):
            return bytes(converted)
    except Exception:
        pass

    if Image is not None:
        image = Image.frombytes("RGB", frame.size, frame.rgb)
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    return bytes(frame.rgb)

