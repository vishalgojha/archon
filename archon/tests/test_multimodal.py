"""Tests for image, audio, and multimodal orchestration helpers."""

from __future__ import annotations

import base64
import io
import os
import wave
from pathlib import Path

import pytest

from archon.config import ArchonConfig
from archon.multimodal import AudioProcessor, ImageInput, ImageProcessor, MultimodalOrchestrator, TranscriptResult

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aN8AAAAASUVORK5CYII="
)
JPEG_1X1 = b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
WEBP_1X1 = (
    b"RIFF"
    + (22).to_bytes(4, "little")
    + b"WEBP"
    + b"VP8X"
    + (10).to_bytes(4, "little")
    + b"\x00\x00\x00\x00"
    + (0).to_bytes(3, "little")
    + (0).to_bytes(3, "little")
)


def _wav_bytes(duration_s: int, sample_rate: int = 8000) -> bytes:
    frames = b"\x00\x00" * duration_s * sample_rate
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    return output.getvalue()


def _png_bytes(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def test_image_processor_load_from_bytes_detects_supported_formats() -> None:
    processor = ImageProcessor()

    jpeg = processor.load_from_bytes(JPEG_1X1)
    png = processor.load_from_bytes(PNG_1X1)
    webp = processor.load_from_bytes(WEBP_1X1)

    assert jpeg.format == "jpeg"
    assert png.format == "png"
    assert webp.format == "webp"


def test_image_processor_resize_if_needed_reduces_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    processor = ImageProcessor()
    oversized = ImageInput(
        input_id="img_big",
        source="upload",
        format="png",
        width=4096,
        height=1024,
        size_bytes=len(_png_bytes(4096, 1024)),
        base64_data=base64.b64encode(_png_bytes(4096, 1024)).decode("ascii"),
    )

    class _FakeImage:
        def __init__(self) -> None:
            self.width = 4096
            self.height = 1024

        def thumbnail(self, size: tuple[int, int]) -> None:
            self.width = size[0]
            self.height = 512

        def save(self, output: io.BytesIO, format: str) -> None:  # noqa: A002
            del format
            output.write(_png_bytes(self.width, self.height))

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

    monkeypatch.setattr("archon.multimodal.image_input._HAS_PILLOW", True)
    monkeypatch.setattr("archon.multimodal.image_input.Image", type("ImageStub", (), {"open": lambda stream: _FakeImage()}))

    resized = processor.resize_if_needed(oversized, max_dimension=2048)

    assert resized.width == 2048
    assert resized.height == 512


def test_image_processor_to_llm_content_shape() -> None:
    processor = ImageProcessor()
    image = processor.load_from_bytes(PNG_1X1)

    payload = processor.to_llm_content(image)

    assert payload["type"] == "image"
    assert payload["source"]["type"] == "base64"
    assert payload["source"]["media_type"] == "image/png"


@pytest.mark.parametrize("source", ["upload", "url", "screenshot", "clipboard"])
def test_image_processor_preserves_source_matrix(source: str) -> None:
    image = ImageProcessor().load_from_bytes(PNG_1X1, source=source)

    assert image.source == source


@pytest.mark.asyncio
async def test_image_processor_load_from_url_uses_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Client:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        async def get(self, url: str):  # type: ignore[no-untyped-def]
            del url
            return type(
                "Response",
                (),
                {
                    "content": PNG_1X1,
                    "headers": {"content-length": str(len(PNG_1X1))},
                    "raise_for_status": lambda self=None: None,
                },
            )()

    monkeypatch.setattr("archon.multimodal.image_input.httpx.AsyncClient", lambda *args, **kwargs: _Client())
    image = await ImageProcessor().load_from_url("https://example.com/image.png")

    assert image.source == "url"
    assert image.format == "png"


def test_audio_processor_load_from_bytes_detects_wav() -> None:
    audio = AudioProcessor().load_from_bytes(_wav_bytes(2))

    assert audio.format == "wav"
    assert audio.duration_s == pytest.approx(2.0, rel=0.02)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (_wav_bytes(1), "wav"),
        (b"ID3\x03\x00\x00\x00\x00\x00\x21", "mp3"),
        (b"OggS\x00\x02" + b"\x00" * 16, "ogg"),
        (b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 12, "m4a"),
        (b"\x1a\x45\xdf\xa3" + b"\x00" * 12, "webm"),
    ],
    ids=["wav", "mp3", "ogg", "m4a", "webm"],
)
def test_audio_processor_format_detection_matrix(payload: bytes, expected: str) -> None:
    audio = AudioProcessor().load_from_bytes(payload)

    assert audio.format == expected


@pytest.mark.asyncio
async def test_audio_processor_transcribe_calls_whisper_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    class _Client:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

        async def post(self, url: str, *, headers, data, files):  # type: ignore[no-untyped-def]
            del url, headers, data, files
            return type(
                "Response",
                (),
                {
                    "raise_for_status": lambda self=None: None,
                    "json": lambda self=None: {"text": "hello world", "language": "en", "segments": [{"start": 0.0, "end": 1.0}]},
                },
            )()

    monkeypatch.setattr("archon.multimodal.audio_input.httpx.AsyncClient", lambda *args, **kwargs: _Client())
    result = await AudioProcessor().transcribe(AudioProcessor().load_from_bytes(_wav_bytes(1)))

    assert result.text == "hello world"
    assert result.method == "openai_whisper_api"


@pytest.mark.asyncio
async def test_audio_processor_transcribe_long_chunks_and_joins() -> None:
    processor = AudioProcessor()
    audio = processor.load_from_bytes(_wav_bytes(65))
    calls: list[str] = []

    async def fake_transcribe(chunk) -> TranscriptResult:  # type: ignore[no-untyped-def]
        calls.append(chunk.input_id)
        return TranscriptResult(
            text=f"chunk-{len(calls)}",
            language="en",
            confidence=0.9,
            segments=[{"index": len(calls)}],
            method="mock",
        )

    processor.transcribe = fake_transcribe  # type: ignore[assignment]
    result = await processor.transcribe_long(audio)

    assert len(calls) == 3
    assert result.text == "chunk-1 chunk-2 chunk-3"
    assert result.method == "mock"


@pytest.mark.asyncio
async def test_audio_processor_fallback_method_when_openai_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("archon.multimodal.audio_input.shutil.which", lambda name: None)

    result = await AudioProcessor().transcribe(AudioProcessor().load_from_bytes(_wav_bytes(1)))

    assert result.method == "local_whisper_unavailable"


@pytest.mark.parametrize(
    ("duration_s", "expected_chunks"),
    [(5, 1), (30, 1), (31, 2), (60, 2), (61, 3), (89, 3), (90, 3), (91, 4)],
)
def test_audio_processor_chunk_matrix(duration_s: int, expected_chunks: int) -> None:
    processor = AudioProcessor()
    audio = processor.load_from_bytes(_wav_bytes(duration_s))

    assert len(processor.chunk_audio(audio, chunk_s=30)) == expected_chunks


@pytest.mark.asyncio
async def test_multimodal_orchestrator_appends_audio_uses_vision_provider_and_extracts_structured_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    config = ArchonConfig()
    config.byok.vision = "openrouter"
    orchestrator = MultimodalOrchestrator(config)

    async def fake_transcribe(audio) -> TranscriptResult:  # type: ignore[no-untyped-def]
        return TranscriptResult(text="spoken words", language="en", confidence=0.9, method="mock")

    async def fake_detect(image, *, session_id, tenant_ctx):  # type: ignore[no-untyped-def]
        del image, session_id, tenant_ctx
        return True

    async def fake_extract(image, *, session_id, tenant_ctx):  # type: ignore[no-untyped-def]
        del image, session_id, tenant_ctx
        return {"rows": 1}

    orchestrator.audio_processor.transcribe = fake_transcribe  # type: ignore[assignment]
    orchestrator.detect_structured_data = fake_detect  # type: ignore[assignment]
    orchestrator.extract_structured_data = fake_extract  # type: ignore[assignment]

    response = await orchestrator.process(
        text="describe this",
        images=[PNG_1X1],
        audio=[_wav_bytes(1)],
        session_id="session-1",
        tenant_ctx={"tenant_id": "tenant-a"},
    )

    assert response.provider == "openai"
    assert response.transcript == "spoken words"
    assert response.structured_data == [{"rows": 1}]
    assert response.content.strip()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("vision_provider", "env_name"),
    [("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"), ("gemini", "GEMINI_API_KEY")],
)
async def test_multimodal_orchestrator_vision_provider_selection_matrix(
    monkeypatch: pytest.MonkeyPatch,
    vision_provider: str,
    env_name: str,
) -> None:
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(env_name, f"{vision_provider}-key")

    config = ArchonConfig()
    config.byok.vision = vision_provider
    orchestrator = MultimodalOrchestrator(config)

    response = await orchestrator.process(
        text="describe",
        images=[PNG_1X1],
        audio=[],
        session_id=f"session-{vision_provider}",
        tenant_ctx={"tenant_id": "tenant-a"},
    )

    assert response.provider == vision_provider
