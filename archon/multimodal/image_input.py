"""Image input processing for multimodal ARCHON workflows."""

from __future__ import annotations

import base64
import io
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

MAX_IMAGE_BYTES = 10 * 1024 * 1024

try:  # pragma: no cover - optional dependency
    from PIL import Image

    _HAS_PILLOW = True
except Exception:  # pragma: no cover - optional dependency fallback
    Image = None  # type: ignore[assignment]
    _HAS_PILLOW = False


def _image_id() -> str:
    return f"img_{uuid.uuid4().hex[:12]}"


@dataclass(slots=True, frozen=True)
class ImageInput:
    """Normalized image input.

    Example:
        >>> ImageInput("img_1", "upload", "jpeg", 10, 10, 100, "abc").source
        'upload'
    """

    input_id: str
    source: str
    format: str
    width: int
    height: int
    size_bytes: int
    base64_data: str


@dataclass(slots=True, frozen=True)
class ImageContext:
    """Combined multimodal image context passed into an LLM request.

    Example:
        >>> ImageContext(images=[], text_prompt="hello").text_prompt
        'hello'
    """

    images: list[ImageInput]
    text_prompt: str


class ImageProcessor:
    """Load, validate, resize, and convert image inputs for LLM use.

    Example:
        >>> processor = ImageProcessor()
        >>> hasattr(processor, "load_from_bytes")
        True
    """

    def load_from_bytes(self, data: bytes, *, source: str = "upload") -> ImageInput:
        """Load one image from raw bytes.

        Example:
            >>> processor = ImageProcessor()
            >>> hasattr(processor, "load_from_bytes")
            True
        """

        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Images larger than 10MB are not supported.")
        fmt = _detect_image_format(data)
        width, height = _image_dimensions(data, fmt)
        return ImageInput(
            input_id=_image_id(),
            source=source,
            format=fmt,
            width=width,
            height=height,
            size_bytes=len(data),
            base64_data=base64.b64encode(data).decode("ascii"),
        )

    async def load_from_url(self, url: str) -> ImageInput:
        """Fetch one remote image with a 10MB hard limit.

        Example:
            >>> processor = ImageProcessor()
            >>> hasattr(processor, "load_from_url")
            True
        """

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(str(url))
            response.raise_for_status()
            content_length = int(response.headers.get("content-length") or 0)
            if content_length > MAX_IMAGE_BYTES or len(response.content) > MAX_IMAGE_BYTES:
                raise ValueError("Images larger than 10MB are not supported.")
            return self.load_from_bytes(response.content, source="url")

    def resize_if_needed(self, image: ImageInput, max_dimension: int = 2048) -> ImageInput:
        """Resize one image if either dimension exceeds the threshold.

        Example:
            >>> processor = ImageProcessor()
            >>> sample = ImageInput("img_1", "upload", "jpeg", 10, 10, 3, "YWJj")
            >>> processor.resize_if_needed(sample, max_dimension=20).width
            10
        """

        if max(image.width, image.height) <= int(max_dimension):
            return image
        if not _HAS_PILLOW or Image is None:
            raise RuntimeError("Pillow is required to resize oversized images.")

        raw = base64.b64decode(image.base64_data)
        with Image.open(io.BytesIO(raw)) as source:
            source.thumbnail((max_dimension, max_dimension))
            output = io.BytesIO()
            fmt = "JPEG" if image.format == "jpeg" else image.format.upper()
            source.save(output, format=fmt)
            resized = output.getvalue()
        return self.load_from_bytes(resized, source=image.source)

    def to_llm_content(self, image: ImageInput) -> dict[str, Any]:
        """Convert one image into Anthropic-compatible multimodal content.

        Example:
            >>> processor = ImageProcessor()
            >>> image = ImageInput("img_1", "upload", "jpeg", 10, 10, 3, "YWJj")
            >>> processor.to_llm_content(image)["type"]
            'image'
        """

        media_type = {
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
        }.get(image.format, "image/jpeg")
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image.base64_data,
            },
        }


def _detect_image_format(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    raise ValueError("Unsupported image format.")


def _image_dimensions(data: bytes, fmt: str) -> tuple[int, int]:
    if fmt == "png":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if fmt == "webp":
        return _webp_dimensions(data)
    if fmt == "jpeg":
        return _jpeg_dimensions(data)
    raise ValueError(f"Unsupported image format '{fmt}'.")


def _webp_dimensions(data: bytes) -> tuple[int, int]:
    chunk = data[12:16]
    if chunk == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    if _HAS_PILLOW and Image is not None:
        with Image.open(io.BytesIO(data)) as image:
            return int(image.width), int(image.height)
    raise ValueError("Unable to determine WebP dimensions without Pillow.")


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    index = 2
    limit = len(data)
    while index < limit - 1:
        while index < limit and data[index] != 0xFF:
            index += 1
        while index < limit and data[index] == 0xFF:
            index += 1
        if index >= limit:
            break
        marker = data[index]
        index += 1
        if marker in {0xD8, 0xD9}:
            continue
        if index + 1 >= limit:
            break
        segment_length = int.from_bytes(data[index : index + 2], "big")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if index + 7 >= limit:
                break
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return width, height
        index += segment_length
    if _HAS_PILLOW and Image is not None:
        with Image.open(io.BytesIO(data)) as image:
            return int(image.width), int(image.height)
    raise ValueError("Unable to determine JPEG dimensions.")
