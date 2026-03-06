"""Screenshot-backed audit trail helpers for agent actions."""

from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from archon.vision.screen_capture import ScreenCapture, ScreenFrame


@dataclass(slots=True)
class AuditEntry:
    """One audit trail entry with screenshots and execution status."""

    action: str
    context: dict[str, Any]
    before_frame: ScreenFrame
    after_frame: ScreenFrame
    timestamp: float
    success: bool
    error: str | None = None


class AuditAgent:
    """Wrap actions with before/after screenshots and persistent manifests."""

    def __init__(self, *, screen_capture: ScreenCapture | None = None) -> None:
        self.screen_capture = screen_capture or ScreenCapture()
        self._entries: list[AuditEntry] = []

    @contextmanager
    def record(self, action_name: str, context: dict[str, Any] | None = None) -> Iterator[None]:
        """Capture before/after screenshots around an action block.

        Example:
            >>> with audit_agent.record("click", {"x": 10, "y": 20}):
            ...     pass
        """

        before_frame = self.screen_capture.capture()
        after_frame = before_frame
        success = False
        error: str | None = None

        try:
            yield
            success = True
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            try:
                after_frame = self.screen_capture.capture()
            except Exception:
                after_frame = before_frame
            self._entries.append(
                AuditEntry(
                    action=action_name,
                    context=dict(context or {}),
                    before_frame=before_frame,
                    after_frame=after_frame,
                    timestamp=time.time(),
                    success=success,
                    error=error,
                )
            )

    def get_audit_trail(self) -> list[AuditEntry]:
        """Return all audit entries.

        Example:
            >>> trail = audit_agent.get_audit_trail()
            >>> isinstance(trail, list)
            True
        """

        return list(self._entries)

    def export_audit(self, path: str | Path) -> Path:
        """Export audit trail as PNG files + JSON manifest.

        Example:
            >>> manifest_path = audit_agent.export_audit("./audit-output")
            >>> manifest_path.name
            'manifest.json'
        """

        output_dir = Path(path)
        output_dir.mkdir(parents=True, exist_ok=True)

        manifest_entries: list[dict[str, Any]] = []
        for index, entry in enumerate(self._entries):
            safe_action = _safe_name(entry.action)
            before_name = f"{index:04d}_{safe_action}_before.png"
            after_name = f"{index:04d}_{safe_action}_after.png"
            (output_dir / before_name).write_bytes(entry.before_frame.image_bytes)
            (output_dir / after_name).write_bytes(entry.after_frame.image_bytes)
            manifest_entries.append(
                {
                    "index": index,
                    "action": entry.action,
                    "context": entry.context,
                    "timestamp": entry.timestamp,
                    "success": entry.success,
                    "error": entry.error,
                    "before_file": before_name,
                    "after_file": after_name,
                    "before_display_id": entry.before_frame.display_id,
                    "after_display_id": entry.after_frame.display_id,
                    "before_size": {
                        "width": entry.before_frame.width,
                        "height": entry.before_frame.height,
                    },
                    "after_size": {
                        "width": entry.after_frame.width,
                        "height": entry.after_frame.height,
                    },
                }
            )

        manifest = {
            "generated_at": time.time(),
            "entry_count": len(manifest_entries),
            "entries": manifest_entries,
        }
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest_path


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned or "action"

