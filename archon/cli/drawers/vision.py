from __future__ import annotations

import io
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import click

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand, approval_prompt
from archon.cli.copy import DRAWER_COPY
from archon.core.approval_gate import ApprovalGate
from archon.providers import ProviderRouter
from archon.vision.action_agent import ActionAgent
from archon.vision.screen_capture import ScreenCapture, ScreenFrame
from archon.vision.ui_parser import UILayout, UIParser
from archon.multimodal.image_input import ImageProcessor

try:  # pragma: no cover - optional dependency
    from PIL import Image, ImageGrab  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency
    Image = None
    ImageGrab = None

DRAWER_ID = "vision"
COMMAND_IDS = ("vision.inspect", "vision.act")
DRAWER_META = DRAWER_COPY[DRAWER_ID]
COMMAND_HELP = DRAWER_META["commands"]


def _get_env_key(name: str, bindings: Any) -> str:
    return str(os.getenv(name) or bindings._read_env_value(name) or "").strip()


def _resolve_vision_provider(bindings: Any, config) -> tuple[str, str]:
    if _get_env_key("ANTHROPIC_API_KEY", bindings):
        provider = "anthropic"
        model = config.byok.vision_model or "claude-3-5-sonnet"
        return provider, model
    provider = "ollama"
    model = config.byok.vision_model or config.byok.ollama_vision_model or "llava:34b"
    return provider, model


def _ensure_ollama_model(bindings: Any, model: str) -> None:
    probe = bindings._probe_ollama(timeout_s=2.0)
    if not probe.get("reachable"):
        raise click.ClickException("Ollama is not reachable for vision model pulls.")
    models = list(probe.get("models", []))
    if model in models:
        return
    subprocess.run(["ollama", "pull", model], check=False)


def _frame_from_file(path: Path) -> ScreenFrame:
    data = path.read_bytes()
    image = ImageProcessor().load_from_bytes(data, source="file")
    return ScreenFrame(
        image_bytes=data,
        width=image.width,
        height=image.height,
        timestamp=time.time(),
        display_id=None,
    )


def _frame_from_clipboard() -> ScreenFrame:
    if ImageGrab is None:
        raise click.ClickException("Clipboard capture requires Pillow.")
    payload = ImageGrab.grabclipboard()
    if payload is None:
        raise click.ClickException("Clipboard does not contain an image.")
    if isinstance(payload, list) and payload:
        return _frame_from_file(Path(payload[0]))
    if Image is not None and isinstance(payload, Image.Image):
        output = io.BytesIO()
        payload.save(output, format="PNG")
        data = output.getvalue()
        return _frame_from_file_bytes(data)
    raise click.ClickException("Clipboard contents are not a supported image.")


def _frame_from_file_bytes(data: bytes) -> ScreenFrame:
    image = ImageProcessor().load_from_bytes(data, source="clipboard")
    return ScreenFrame(
        image_bytes=data,
        width=image.width,
        height=image.height,
        timestamp=time.time(),
        display_id=None,
    )


def _capture_frame(file_path: Path | None, clipboard: bool) -> ScreenFrame:
    if file_path is not None and clipboard:
        raise click.ClickException("Use either --file or --clipboard, not both.")
    if file_path is not None:
        return _frame_from_file(file_path)
    if clipboard:
        return _frame_from_clipboard()
    return ScreenCapture().capture()


def _layout_payload(layout: UILayout, frame: ScreenFrame) -> dict[str, Any]:
    return {
        "provider": layout.provider,
        "model": layout.model,
        "image_hash": layout.image_hash,
        "frame": {"width": frame.width, "height": frame.height},
        "parse_error": layout.parse_error,
        "elements": [
            {
                "type": element.type,
                "text": element.text,
                "bounds": {
                    "x": element.bounds.x,
                    "y": element.bounds.y,
                    "width": element.bounds.width,
                    "height": element.bounds.height,
                },
                "confidence": element.confidence,
                "element_id": element.element_id,
            }
            for element in layout.elements
        ],
    }


def _extract_target_text(instruction: str) -> str:
    match = re.search(r"\"([^\"]+)\"|'([^']+)'", instruction)
    if match:
        return (match.group(1) or match.group(2) or "").strip()
    return instruction.strip()


def _score_element(text: str, query: str) -> int:
    if not text or not query:
        return 0
    lower_text = text.lower()
    lower_query = query.lower()
    if lower_query == lower_text:
        return 1000
    if lower_query in lower_text:
        return 500 + len(lower_query)
    words = set(re.findall(r"\w+", lower_query))
    if not words:
        return 0
    overlap = words.intersection(set(re.findall(r"\w+", lower_text)))
    return len(overlap) * 10


def _select_element(layout: UILayout, instruction: str) -> tuple[str, int, int] | None:
    query = _extract_target_text(instruction)
    best = None
    best_score = 0
    for element in layout.elements:
        score = _score_element(element.text, query)
        if score > best_score:
            best_score = score
            best = element
    if best is None:
        return None
    center_x = best.bounds.x + max(1, best.bounds.width) // 2
    center_y = best.bounds.y + max(1, best.bounds.height) // 2
    return best.element_id, center_x, center_y


def _infer_action(instruction: str) -> tuple[str, dict[str, Any]]:
    lowered = instruction.lower()
    if "scroll" in lowered:
        direction = "down" if "down" in lowered else "up"
        amount = 3
        match = re.search(r"scroll\s+(\d+)", lowered)
        if match:
            amount = max(1, int(match.group(1)))
        clicks = -amount if direction == "down" else amount
        return "scroll", {"clicks": clicks}
    if "type" in lowered:
        match = re.search(r"type\s+\"([^\"]+)\"|type\s+'([^']+)'", instruction, re.IGNORECASE)
        text = (match.group(1) or match.group(2)) if match else instruction.split("type", 1)[-1].strip()
        return "type", {"text": text}
    return "click", {}


def _vision_event_sink(gate: ApprovalGate):  # type: ignore[no-untyped-def]
    async def sink(event):
        if str(event.get("type", "")).strip().lower() == "approval_required":
            approval_prompt(gate=gate, event=event)

    return sink


class _Inspect(ArchonCommand):
    command_id = COMMAND_IDS[0]

    async def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        file_path: Path | None,
        clipboard: bool,
        config_path: str,
    ):
        config = session.run_step(0, self.bindings._load_config, config_path)
        frame = session.run_step(1, _capture_frame, file_path, clipboard)
        provider, model = _resolve_vision_provider(self.bindings, config)
        if provider == "ollama":
            session.run_step(2, _ensure_ollama_model, self.bindings, model)
        router = ProviderRouter(config=config, live_mode=True)
        parser = UIParser(router)
        layout = await session.run_step_async(
            3,
            parser.parse_multimodal,
            frame,
            provider_override=provider,
            model_override=model,
        )
        payload = _layout_payload(layout, frame)
        session.print(renderer.detail_panel(self.command_id, [json.dumps(payload, indent=2)]))
        return {
            "element_count": len(layout.elements),
            "provider": layout.provider or provider,
            "model": layout.model or model,
            "status": "ok" if layout.parse_error is None else "parse_error",
        }


class _Act(ArchonCommand):
    command_id = COMMAND_IDS[1]

    async def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        instruction: str,
        file_path: Path | None,
        clipboard: bool,
        config_path: str,
    ):
        config = session.run_step(0, self.bindings._load_config, config_path)
        frame = session.run_step(1, _capture_frame, file_path, clipboard)
        provider, model = _resolve_vision_provider(self.bindings, config)
        if provider == "ollama":
            session.run_step(2, _ensure_ollama_model, self.bindings, model)
        router = ProviderRouter(config=config, live_mode=True)
        parser = UIParser(router)
        layout = await session.run_step_async(
            3,
            parser.parse_multimodal,
            frame,
            provider_override=provider,
            model_override=model,
        )
        target = _select_element(layout, instruction)
        if target is None:
            raise click.ClickException("No matching UI element found for instruction.")
        element_id, x, y = target
        action_type, details = _infer_action(instruction)
        gate = ApprovalGate()
        action_agent = ActionAgent(gate)
        if action_type == "scroll":
            await gate.check(
                action="gui_form_submit",
                context={
                    "instruction": instruction,
                    "element_id": element_id,
                    "x": x,
                    "y": y,
                    "event_sink": _vision_event_sink(gate),
                },
                action_id=f"gui-{uuid.uuid4().hex[:12]}",
            )
            await action_agent.scroll(x, y, int(details["clicks"]))
        elif action_type == "type":
            await action_agent.click(x, y, event_sink=_vision_event_sink(gate))
            await action_agent.type_text(details["text"])
        else:
            await action_agent.click(x, y, event_sink=_vision_event_sink(gate))
        last_entry = action_agent.get_action_log()[-1] if action_agent.get_action_log() else None
        return {
            "action": action_type,
            "element_id": element_id,
            "x": x,
            "y": y,
            "provider": layout.provider or provider,
            "model": layout.model or model,
            "confirmed": bool(last_entry is not None and last_entry.success),
        }


def build_group(bindings):
    @click.group(
        name=DRAWER_ID,
        invoke_without_command=True,
        help=str(DRAWER_META["tagline"]),
    )
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("inspect", help=str(COMMAND_HELP[COMMAND_IDS[0]]))
    @click.option("--file", "file_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option("--clipboard", is_flag=True, default=False)
    @click.option("--config", "config_path", default="config.archon.yaml")
    def inspect_command(file_path: Path | None, clipboard: bool, config_path: str) -> None:
        _Inspect(bindings).invoke(file_path=file_path, clipboard=clipboard, config_path=config_path)

    @group.command("act", help=str(COMMAND_HELP[COMMAND_IDS[1]]))
    @click.argument("instruction")
    @click.option("--file", "file_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option("--clipboard", is_flag=True, default=False)
    @click.option("--config", "config_path", default="config.archon.yaml")
    def act_command(
        instruction: str, file_path: Path | None, clipboard: bool, config_path: str
    ) -> None:
        _Act(bindings).invoke(
            instruction=instruction,
            file_path=file_path,
            clipboard=clipboard,
            config_path=config_path,
        )

    return group
