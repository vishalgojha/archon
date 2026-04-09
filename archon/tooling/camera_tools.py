"""Camera tools for laptop webcam access."""

from __future__ import annotations

import base64
import io
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any

from archon.tooling.base import BaseTool, ToolResult
from archon.tooling.registry import ToolRegistry
from archon.tooling.safety import PathPolicy

ASCII_CHARS = list(" .:-=+*#%@")
ASCII_PALETTE = ASCII_CHARS * 3


@dataclass
class CameraFrame:
    """A captured camera frame."""

    timestamp: float
    width: int
    height: int
    data: bytes
    format: str = "jpeg"


class CameraTool(BaseTool):
    """Capture images from laptop camera."""

    name: str = "camera_capture"
    description: str = "Capture an image from the laptop camera."
    input_schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.input_schema = {
            "type": "object",
            "properties": {
                "save_path": {"type": "string", "description": "Path to save captured image."},
                "quality": {"type": "number", "description": "JPEG quality (0-100)."},
            },
        }

    async def execute(self, **kwargs) -> ToolResult:
        save_path = kwargs.get("save_path")
        quality = int(kwargs.get("quality", 85) or 85)

        try:
            import cv2
        except ImportError:
            return ToolResult(ok=False, output="opencv-python not installed: pip install opencv-python")

        try:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return ToolResult(ok=False, output="Cannot open camera")

            ret, frame = cap.read()
            cap.release()

            if not ret:
                return ToolResult(ok=False, output="Failed to capture frame")

            height, width = frame.shape[:2]

            if save_path:
                cv2.imwrite(save_path, frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
                return ToolResult(ok=True, output=f"Saved to {save_path}")

            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            b64 = base64.b64encode(buffer).decode('utf-8')

            return ToolResult(
                ok=True,
                output=f"data:image/jpeg;base64,{b64}",
                metadata={"width": width, "height": height}
            )

        except Exception as exc:
            return ToolResult(ok=False, output=f"Camera error: {exc}")


class CameraStreamTool(BaseTool):
    """Stream camera frames for real-time vision."""

    name: str = "camera_stream"
    description: str = "Start a camera stream for real-time analysis."
    input_schema: dict[str, Any] = None  # type: ignore[assignment]

    _stream_thread: threading.Thread | None = None
    _stream_active: bool = False
    _latest_frame: bytes | None = None

    def __post_init__(self) -> None:
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "start, stop, or capture"},
                "max_frames": {"type": "number", "description": "Max frames to capture."},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> ToolResult:
        action = str(kwargs.get("action", "")).strip().lower()

        if action == "start":
            return self._start_stream(kwargs)
        elif action == "stop":
            return self._stop_stream()
        elif action == "capture":
            return self._capture_frame()
        else:
            return ToolResult(ok=False, output="action must be: start, stop, or capture")

    def _start_stream(self, kwargs) -> ToolResult:

        if self._stream_active:
            return ToolResult(ok=False, output="Stream already active")

        max_frames = int(kwargs.get("max_frames", 10) or 10)
        self._stream_active = True

        def stream_loop():
            try:
                import cv2
                cap = cv2.VideoCapture(0)
                frame_count = 0

                while self._stream_active and frame_count < max_frames:
                    ret, frame = cap.read()
                    if ret:
                        _, buffer = cv2.imencode('.jpg', frame)
                        CameraStreamTool._latest_frame = buffer.tobytes()
                        frame_count += 1
                    time.sleep(0.1)

                cap.release()
            except Exception:
                pass

        self._stream_thread = threading.Thread(target=stream_loop, daemon=True)
        self._stream_thread.start()

        return ToolResult(ok=True, output=f"Stream started (max {max_frames} frames)")

    def _stop_stream(self) -> ToolResult:
        self._stream_active = False
        if self._stream_thread:
            self._stream_thread.join(timeout=2)
        CameraStreamTool._latest_frame = None
        return ToolResult(ok=True, output="Stream stopped")

    def _capture_frame(self) -> ToolResult:
        if self._latest_frame:
            b64 = base64.b64encode(self._latest_frame).decode('utf-8')
            return ToolResult(
                ok=True,
                output=f"data:image/jpeg;base64,{b64}",
                metadata={"streaming": self._stream_active}
            )
        return ToolResult(ok=False, output="No frame captured - start stream first")


class AsciiVideoTool(BaseTool):
    """Render camera as ASCII art - the never-been-tried terminal experience."""

    name: str = "ascii_video"
    description: str = "Stream camera as ASCII art in terminal."
    input_schema: dict[str, Any] = None  # type: ignore[assignment]

    _video_active: bool = False
    _video_thread: threading.Thread | None = None

    def __post_init__(self) -> None:
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "start or stop"},
                "width": {"type": "number", "description": "ASCII width (default 80)"},
                "height": {"type": "number", "description": "ASCII height (default 40)"},
                "fps": {"type": "number", "description": "Frames per second"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> ToolResult:
        action = str(kwargs.get("action", "")).strip().lower()

        if action == "start":
            width = int(kwargs.get("width", 80) or 80)
            height = int(kwargs.get("height", 40) or 40)
            fps = float(kwargs.get("fps", 10) or 10)
            return self._start_ascii_video(width, height, fps)
        elif action == "stop":
            return self._stop_ascii_video()
        else:
            return ToolResult(ok=False, output="action must be: start or stop")

    def _start_ascii_video(self, width: int, height: int, fps: float) -> ToolResult:
        if self._video_active:
            return ToolResult(ok=False, output="ASCII video already running")

        self._video_active = True

        def video_loop():
            try:
                import cv2
                import numpy as np

                cap = cv2.VideoCapture(0)
                if not cap.isOpened():
                    return

                char_width = 8
                char_height = 16

                while self._video_active:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                    new_width = width * char_width
                    new_height = height * char_height
                    frame = cv2.resize(frame, (new_width, new_height))

                    ascii_frame = []
                    for y in range(0, new_height, char_height):
                        row = ""
                        for x in range(0, new_width, char_width):
                            region = frame[y:y+char_height, x:x+char_width]
                            avg = np.mean(region)
                            char_idx = int((avg / 255) * len(ASCII_CHARS) - 1)
                            char_idx = max(0, min(char_idx, len(ASCII_CHARS) - 1))
                            row += ASCII_CHARS[char_idx]
                        ascii_frame.append(row)

                    output = "\033[2J\033[H" + "\n".join(ascii_frame)

                    print(output, end='\r')
                    time.sleep(1 / fps)

                cap.release()

            except ImportError:
                print("opencv-python needed: pip install opencv-python")
            except Exception:
                pass

        self._video_thread = threading.Thread(target=video_loop, daemon=True)
        self._video_thread.start()

        return ToolResult(
            ok=True,
            output=f"ASCII video started: {width}x{height} @ {fps}fps. Use action=stop to end."
        )

    def _stop_ascii_video(self) -> ToolResult:
        self._video_active = False
        if self._video_thread:
            self._video_thread.join(timeout=2)
        print("\n\033[2J\033[HASCII video stopped")
        return ToolResult(ok=True, output="ASCII video stopped")


class ScreenCaptureTool(BaseTool):
    """Capture laptop screen."""

    name: str = "screen_capture"
    description: str = "Capture the laptop screen."
    input_schema: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.input_schema = {
            "type": "object",
            "properties": {
                "save_path": {"type": "string", "description": "Path to save screenshot."},
            },
        }

    async def execute(self, **kwargs) -> ToolResult:
        save_path = kwargs.get("save_path")

        if os.name == "nt":
            return self._capture_windows(save_path)
        else:
            return self._capture_unix(save_path)

    def _capture_windows(self, save_path) -> ToolResult:
        try:
            import pyautogui
        except ImportError:
            return ToolResult(ok=False, output="pyautogui not installed: pip install pyautogui")

        try:
            img = pyautogui.screenshot()
            if save_path:
                img.save(save_path)
                return ToolResult(ok=True, output=f"Saved to {save_path}")

            buf = io.BytesIO()
            img.save(buf, format='PNG')
            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
            return ToolResult(ok=True, output=f"data:image/png;base64,{b64}")

        except Exception as exc:
            return ToolResult(ok=False, output=f"Screenshot error: {exc}")

    def _capture_unix(self, save_path) -> ToolResult:
        try:
            result = subprocess.run(
                ["scrot", "-b", save_path if save_path else "/tmp/archon_screenshot.png"],
                capture_output=True,
                timeout=5
            )
            if result.returncode != 0:
                return ToolResult(ok=False, output=f"scrot failed: {result.stderr.decode()}")

            if save_path:
                return ToolResult(ok=True, output=f"Saved to {save_path}")

            with open("/tmp/archon_screenshot.png", "rb") as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
            return ToolResult(ok=True, output=f"data:image/png;base64,{b64}")

        except FileNotFoundError:
            return ToolResult(ok=False, output="scrot not installed: apt install scrot")
        except Exception as exc:
            return ToolResult(ok=False, output=f"Screenshot error: {exc}")


def build_camera_tool_registry(policy: PathPolicy | None = None) -> ToolRegistry:
    tools = [
        CameraTool(),
        CameraStreamTool(),
        AsciiVideoTool(),
        ScreenCaptureTool(),
    ]
    return ToolRegistry(tools)
