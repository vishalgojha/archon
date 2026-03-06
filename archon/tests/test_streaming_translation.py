"""Tests for real-time translation streaming and webchat protocol wiring."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from archon.interfaces.webchat.server import create_webchat_app
from archon.vernacular.streaming import StreamingTranslator, TranslatedToken, TranslationBuffer


@pytest.fixture(autouse=True)
def _jwt_secret_fixture() -> None:
    previous = os.environ.get("ARCHON_JWT_SECRET")
    os.environ["ARCHON_JWT_SECRET"] = previous or "archon-dev-secret-change-me-32-bytes"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("ARCHON_JWT_SECRET", None)
        else:
            os.environ["ARCHON_JWT_SECRET"] = previous


async def _token_stream(tokens: list[str]) -> AsyncGenerator[str]:
    for token in tokens:
        yield token


@pytest.mark.asyncio
async def test_translation_buffer_flushes_on_boundary_and_resets() -> None:
    buffer = TranslationBuffer(max_size=200, flush_on={".", "!"})

    assert buffer.add("hello") == []
    flushed = buffer.add(" world.")
    assert flushed == [("hello world.", "boundary")]
    assert buffer.size == 0


@pytest.mark.asyncio
async def test_translation_buffer_flushes_on_max_size() -> None:
    buffer = TranslationBuffer(max_size=5, flush_on={"."})
    flushed = buffer.add("abcde")
    assert flushed == [("abcde", "max_size")]
    assert buffer.size == 0


@pytest.mark.asyncio
async def test_stream_translate_same_language_passthrough() -> None:
    translator = StreamingTranslator(
        translate_text_fn=lambda text, source, target: f"[{source}->{target}]{text}"
    )
    chunks = []
    async for original, token in translator.stream_translate_with_metadata(
        _token_stream(["Hello world."]),
        source_lang="en",
        target_lang="en",
    ):
        chunks.append((original, token))

    assert len(chunks) == 1
    original, token = chunks[0]
    assert original == "Hello world."
    assert token.content == "Hello world."
    assert token.was_translated is False
    assert token.buffer_flush_reason == "boundary"


@pytest.mark.asyncio
async def test_stream_translate_flushes_remaining_buffer_at_stream_end() -> None:
    translator = StreamingTranslator(translate_text_fn=lambda text, _s, _t: text.upper())
    emitted: list[TranslatedToken] = []
    async for _original, token in translator.stream_translate_with_metadata(
        _token_stream(["unfinished sentence"]),
        source_lang="en",
        target_lang="es",
    ):
        emitted.append(token)

    assert len(emitted) == 1
    assert emitted[0].buffer_flush_reason == "stream_end"
    assert emitted[0].content == "UNFINISHED SENTENCE"


@pytest.mark.asyncio
async def test_stream_detect_and_translate_uses_first_100_chars_for_detection() -> None:
    detector_samples: list[str] = []

    def detect_language(sample: str) -> str:
        detector_samples.append(sample)
        return "es"

    translator = StreamingTranslator(
        detect_language_fn=detect_language,
        translate_text_fn=lambda text, source, target: f"{target}:{text}",
        default_source_lang="en",
    )
    tokens = ["a" * 60, "b" * 60, " final."]
    emitted: list[TranslatedToken] = []
    async for token in translator.stream_detect_and_translate(_token_stream(tokens)):
        emitted.append(token)

    assert detector_samples
    assert len(detector_samples[0]) == 100
    assert all(token.target_lang == "es" for token in emitted)
    assert any(token.content.startswith("es:") for token in emitted)


def test_websocket_translation_mode_off_emits_plain_tokens() -> None:
    app = create_webchat_app()
    with TestClient(app) as client:
        token_payload = client.post("/token", json={}).json()
        token = token_payload["token"]
        session_id = token_payload["session"]["session_id"]
        with client.websocket_connect(f"/ws/{session_id}?token={token}") as ws:
            restored = ws.receive_json()
            assert restored["type"] == "session_restored"
            ws.send_json({"type": "message", "content": "Hello", "translation_mode": "off"})

            seen_assistant_token = False
            for _ in range(200):
                frame = ws.receive_json()
                if frame.get("type") == "assistant_token":
                    seen_assistant_token = True
                if frame.get("type") == "done":
                    break

            assert seen_assistant_token is True


def test_websocket_translation_mode_lang_emits_lang_tokens() -> None:
    app = create_webchat_app()
    with TestClient(app) as client:
        token_payload = client.post("/token", json={}).json()
        token = token_payload["token"]
        session_id = token_payload["session"]["session_id"]
        with client.websocket_connect(f"/ws/{session_id}?token={token}") as ws:
            _ = ws.receive_json()
            ws.send_json({"type": "message", "content": "Hello world", "translation_mode": "es"})

            translated_frames: list[dict[str, object]] = []
            for _ in range(200):
                frame = ws.receive_json()
                if frame.get("type") == "token":
                    translated_frames.append(frame)
                if frame.get("type") == "done":
                    break

            assert translated_frames
            assert all(frame.get("lang") == "es" for frame in translated_frames)
            assert all("content" in frame and "original" in frame for frame in translated_frames)
