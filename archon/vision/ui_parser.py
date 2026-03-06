"""Vision UI parsing through the BYOK provider router."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from archon.providers import ProviderRouter
from archon.vision.screen_capture import ScreenFrame

UIElementType = Literal[
    "button", "input", "link", "text", "image", "checkbox", "dropdown", "unknown"
]
SUPPORTED_UI_TYPES: set[str] = {
    "button",
    "input",
    "link",
    "text",
    "image",
    "checkbox",
    "dropdown",
    "unknown",
}

DEFAULT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "type": {"enum": sorted(SUPPORTED_UI_TYPES)},
            "text": {"type": "string"},
            "bounds": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
                "required": ["x", "y", "width", "height"],
            },
            "confidence": {"type": "number"},
            "element_id": {"type": "string"},
        },
        "required": ["type", "text", "bounds"],
    },
}

DEFAULT_PARSE_PROMPT = (
    "You are a GUI parser. Analyze the screenshot and return ONLY JSON.\n"
    "Output must strictly match this schema:\n"
    "{response_schema}\n"
    "Rules:\n"
    "- Return a JSON array (or object with `elements` array).\n"
    "- Each element needs type, text, bounds (x,y,width,height), confidence, element_id.\n"
    "- Use `unknown` if type is unclear.\n"
    "Image metadata: width={frame_width}, height={frame_height}\n"
    "Screenshot (base64 PNG):\n"
    "{image_b64}\n"
)


@dataclass(slots=True, frozen=True)
class Bounds:
    """Rectangle bounds for one UI element."""

    x: int
    y: int
    width: int
    height: int


@dataclass(slots=True, frozen=True)
class UIElement:
    """Parsed UI element."""

    type: UIElementType
    text: str
    bounds: Bounds
    confidence: float
    element_id: str


@dataclass(slots=True)
class UILayout:
    """Parsed UI layout from one screenshot."""

    elements: list[UIElement] = field(default_factory=list)
    image_hash: str = ""
    parsed_at: float = field(default_factory=time.time)
    raw_response: str = ""
    parse_error: str | None = None
    provider: str | None = None
    model: str | None = None


class UIParser:
    """Vision parser that extracts structured UI elements from screenshots."""

    def __init__(
        self,
        router: ProviderRouter,
        *,
        role: str = "vision",
        parse_prompt: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> None:
        self.router = router
        self.role = role
        self.parse_prompt = parse_prompt or DEFAULT_PARSE_PROMPT
        self.response_schema = response_schema or dict(DEFAULT_RESPONSE_SCHEMA)
        self._cache: dict[str, UILayout] = {}

    async def parse(self, frame: ScreenFrame) -> UILayout:
        """Parse one screenshot into a UI layout.

        Example:
            >>> parser = UIParser(router)
            >>> layout = await parser.parse(frame)
            >>> isinstance(layout.elements, list)
            True
        """

        image_hash = hashlib.sha256(frame.image_bytes).hexdigest()
        cached = self._cache.get(image_hash)
        if cached is not None:
            return cached

        image_b64 = base64.b64encode(frame.image_bytes).decode("ascii")
        prompt = self._build_prompt(
            image_b64=image_b64,
            frame_width=frame.width,
            frame_height=frame.height,
        )
        response = await self.router.invoke(role=self.role, prompt=prompt)
        layout = _parse_layout_response(
            response.text,
            image_hash=image_hash,
            provider=response.provider,
            model=response.model,
        )
        self._cache[image_hash] = layout
        return layout

    def clear_cache(self) -> None:
        """Clear parse cache."""

        self._cache.clear()

    def _build_prompt(self, *, image_b64: str, frame_width: int, frame_height: int) -> str:
        schema_text = json.dumps(self.response_schema, separators=(",", ":"))
        variables: dict[str, str | int] = {
            "image_b64": image_b64,
            "response_schema": schema_text,
            "frame_width": frame_width,
            "frame_height": frame_height,
        }
        return self.parse_prompt.format_map(_SafeFormatDict(variables))


def _parse_layout_response(
    raw_response: str,
    *,
    image_hash: str,
    provider: str | None,
    model: str | None,
) -> UILayout:
    payload, error = _decode_json_payload(raw_response)
    if error is not None:
        return UILayout(
            elements=[],
            image_hash=image_hash,
            raw_response=raw_response,
            parse_error=error,
            provider=provider,
            model=model,
        )

    elements = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            continue
        bounds = _parse_bounds(row.get("bounds"))
        if bounds is None:
            continue
        element_type = _normalize_type(row.get("type"))
        text = str(row.get("text", ""))
        confidence = _normalize_confidence(row.get("confidence"))
        element_id = str(row.get("element_id") or row.get("id") or f"element-{index + 1}")
        elements.append(
            UIElement(
                type=element_type,
                text=text,
                bounds=bounds,
                confidence=confidence,
                element_id=element_id,
            )
        )

    return UILayout(
        elements=elements,
        image_hash=image_hash,
        raw_response=raw_response,
        provider=provider,
        model=model,
    )


def _decode_json_payload(raw_response: str) -> tuple[list[Any], str | None]:
    attempts = [_strip_code_fences(raw_response), raw_response]
    for candidate in attempts:
        payload = _load_json_candidate(candidate)
        if payload is not None:
            return payload, None

    bracket_start = raw_response.find("[")
    bracket_end = raw_response.rfind("]")
    if bracket_start != -1 and bracket_end > bracket_start:
        payload = _load_json_candidate(raw_response[bracket_start : bracket_end + 1])
        if payload is not None:
            return payload, None

    return [], "malformed_json"


def _load_json_candidate(candidate: str) -> list[Any] | None:
    text = candidate.strip()
    if not text:
        return []
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return None

    if isinstance(decoded, list):
        return decoded
    if isinstance(decoded, dict):
        elements = decoded.get("elements")
        if isinstance(elements, list):
            return elements
        return [decoded]
    return None


def _strip_code_fences(raw_response: str) -> str:
    text = raw_response.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) <= 2:
        return text.strip("`")
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def _parse_bounds(value: Any) -> Bounds | None:
    if isinstance(value, dict):
        try:
            x = int(value.get("x", value.get("left", 0)))
            y = int(value.get("y", value.get("top", 0)))
            width = int(value.get("width", value.get("w", 0)))
            height = int(value.get("height", value.get("h", 0)))
        except (TypeError, ValueError):
            return None
        return Bounds(x=x, y=y, width=max(0, width), height=max(0, height))

    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            x = int(value[0])
            y = int(value[1])
            width = int(value[2])
            height = int(value[3])
        except (TypeError, ValueError):
            return None
        return Bounds(x=x, y=y, width=max(0, width), height=max(0, height))

    return None


def _normalize_type(value: Any) -> UIElementType:
    candidate = str(value or "unknown").strip().lower()
    if candidate not in SUPPORTED_UI_TYPES:
        return "unknown"
    return candidate  # type: ignore[return-value]


def _normalize_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.0
    return max(0.0, min(1.0, confidence))


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
