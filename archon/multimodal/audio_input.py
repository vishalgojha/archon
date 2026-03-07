"""Audio input processing and transcription for multimodal ARCHON workflows."""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
import uuid
import wave
from dataclasses import dataclass, field
from typing import Any

import httpx


def _audio_id() -> str:
    return f"aud_{uuid.uuid4().hex[:12]}"


@dataclass(slots=True, frozen=True)
class AudioInput:
    """Normalized audio input.

    Example:
        >>> AudioInput("aud_1", "wav", 1.0, 16000, 12, b"abc").format
        'wav'
    """

    input_id: str
    format: str
    duration_s: float
    sample_rate: int
    size_bytes: int
    data: bytes


@dataclass(slots=True, frozen=True)
class TranscriptResult:
    """Transcript output for one audio input.

    Example:
        >>> TranscriptResult("hello", "en", 0.9, [], "api").language
        'en'
    """

    text: str
    language: str
    confidence: float
    segments: list[dict[str, Any]] = field(default_factory=list)
    method: str = "none"


class AudioProcessor:
    """Load, chunk, and transcribe audio inputs.

    Example:
        >>> processor = AudioProcessor()
        >>> hasattr(processor, "load_from_bytes")
        True
    """

    def load_from_bytes(self, data: bytes) -> AudioInput:
        """Load one audio input from bytes.

        Example:
            >>> processor = AudioProcessor()
            >>> hasattr(processor, "load_from_bytes")
            True
        """

        fmt = _detect_audio_format(data)
        duration_s = 0.0
        sample_rate = 0
        if fmt == "wav":
            with wave.open(io.BytesIO(data), "rb") as wav:
                sample_rate = int(wav.getframerate())
                frames = int(wav.getnframes())
                duration_s = frames / float(sample_rate or 1)
        return AudioInput(
            input_id=_audio_id(),
            format=fmt,
            duration_s=float(duration_s),
            sample_rate=int(sample_rate),
            size_bytes=len(data),
            data=data,
        )

    async def transcribe(
        self,
        audio: AudioInput,
        language: str | None = None,
    ) -> TranscriptResult:
        """Transcribe one audio input with Whisper API or local fallback.

        Example:
            >>> processor = AudioProcessor()
            >>> hasattr(processor, "transcribe")
            True
        """

        api_key = str(os.getenv("OPENAI_API_KEY", "")).strip()
        if api_key:
            return await self._transcribe_via_api(audio, api_key=api_key, language=language)
        return await self._transcribe_via_local(audio, language=language)

    def chunk_audio(self, audio: AudioInput, chunk_s: int = 30) -> list[AudioInput]:
        """Split one long audio input into fixed-duration chunks.

        Example:
            >>> processor = AudioProcessor()
            >>> short = AudioInput("aud_1", "wav", 5.0, 16000, 4, b"1234")
            >>> len(processor.chunk_audio(short))
            1
        """

        if audio.duration_s <= float(chunk_s) or audio.duration_s <= 0:
            return [audio]
        if audio.format == "wav":
            return _chunk_wav(audio, chunk_s=chunk_s)
        segments = int((audio.duration_s + chunk_s - 1) // chunk_s)
        chunks: list[AudioInput] = []
        for index in range(segments):
            start = int(len(audio.data) * (index / segments))
            end = int(len(audio.data) * ((index + 1) / segments))
            duration = min(float(chunk_s), max(0.0, audio.duration_s - (index * chunk_s)))
            chunks.append(
                AudioInput(
                    input_id=_audio_id(),
                    format=audio.format,
                    duration_s=duration,
                    sample_rate=audio.sample_rate,
                    size_bytes=end - start,
                    data=audio.data[start:end],
                )
            )
        return chunks

    async def transcribe_long(self, audio: AudioInput) -> TranscriptResult:
        """Chunk and transcribe one long recording.

        Example:
            >>> processor = AudioProcessor()
            >>> hasattr(processor, "transcribe_long")
            True
        """

        pieces = self.chunk_audio(audio, chunk_s=30)
        if len(pieces) == 1:
            return await self.transcribe(audio)
        transcripts = [await self.transcribe(piece) for piece in pieces]
        text = " ".join(item.text.strip() for item in transcripts if item.text.strip()).strip()
        language = next((item.language for item in transcripts if item.language), "unknown")
        confidence = sum(item.confidence for item in transcripts) / max(1, len(transcripts))
        segments = [segment for item in transcripts for segment in item.segments]
        method = "+".join(dict.fromkeys(item.method for item in transcripts))
        return TranscriptResult(
            text=text,
            language=language,
            confidence=round(confidence, 4),
            segments=segments,
            method=method,
        )

    async def _transcribe_via_api(
        self,
        audio: AudioInput,
        *,
        api_key: str,
        language: str | None = None,
    ) -> TranscriptResult:
        files = {"file": ("audio.bin", audio.data, _mime_type(audio.format))}
        data = {"model": "whisper-1"}
        if language:
            data["language"] = str(language)
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                data=data,
                files=files,
            )
            response.raise_for_status()
            payload = response.json()
        return TranscriptResult(
            text=str(payload.get("text") or "").strip(),
            language=str(payload.get("language") or language or "unknown"),
            confidence=float(payload.get("confidence") or 0.9),
            segments=list(payload.get("segments") or []),
            method="openai_whisper_api",
        )

    async def _transcribe_via_local(
        self,
        audio: AudioInput,
        *,
        language: str | None = None,
    ) -> TranscriptResult:
        whisper_binary = shutil.which("whisper")
        if whisper_binary is None:
            return TranscriptResult(
                text="",
                language=str(language or "unknown"),
                confidence=0.0,
                segments=[],
                method="local_whisper_unavailable",
            )
        with tempfile.TemporaryDirectory() as tmp_dir:
            audio_path = os.path.join(tmp_dir, f"{audio.input_id}.{audio.format}")
            txt_path = os.path.join(tmp_dir, audio.input_id)
            with open(audio_path, "wb") as handle:
                handle.write(audio.data)
            cmd = [whisper_binary, audio_path, "--model", "base", "--output_format", "json", "--output_dir", tmp_dir]
            if language:
                cmd.extend(["--language", str(language)])
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                return TranscriptResult(
                    text=result.stdout.strip() or result.stderr.strip(),
                    language=str(language or "unknown"),
                    confidence=0.0,
                    segments=[],
                    method="local_whisper_failed",
                )
            json_path = f"{txt_path}.json"
            if not os.path.exists(json_path):
                return TranscriptResult(
                    text="",
                    language=str(language or "unknown"),
                    confidence=0.0,
                    segments=[],
                    method="local_whisper_missing_output",
                )
            payload = json.loads(open(json_path, "r", encoding="utf-8").read())
        return TranscriptResult(
            text=str(payload.get("text") or "").strip(),
            language=str(payload.get("language") or language or "unknown"),
            confidence=float(payload.get("confidence") or 0.7),
            segments=list(payload.get("segments") or []),
            method="local_whisper",
        )


def _detect_audio_format(data: bytes) -> str:
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"ID3") or data[:2] == b"\xff\xfb":
        return "mp3"
    if data.startswith(b"OggS"):
        return "ogg"
    if data[4:8] == b"ftyp":
        major = data[8:12]
        if major in {b"M4A ", b"isom", b"mp42"}:
            return "m4a"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    raise ValueError("Unsupported audio format.")


def _mime_type(fmt: str) -> str:
    return {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "ogg": "audio/ogg",
        "m4a": "audio/mp4",
        "webm": "audio/webm",
    }.get(fmt, "application/octet-stream")


def _chunk_wav(audio: AudioInput, *, chunk_s: int) -> list[AudioInput]:
    with wave.open(io.BytesIO(audio.data), "rb") as wav:
        params = wav.getparams()
        frame_rate = int(wav.getframerate())
        frames_per_chunk = frame_rate * int(chunk_s)
        chunks: list[AudioInput] = []
        index = 0
        while True:
            frames = wav.readframes(frames_per_chunk)
            if not frames:
                break
            output = io.BytesIO()
            with wave.open(output, "wb") as writer:
                writer.setparams(params)
                writer.writeframes(frames)
            chunk_bytes = output.getvalue()
            duration = len(frames) / float(frame_rate * params.sampwidth * params.nchannels or 1)
            chunks.append(
                AudioInput(
                    input_id=f"{audio.input_id}_{index}",
                    format="wav",
                    duration_s=duration,
                    sample_rate=frame_rate,
                    size_bytes=len(chunk_bytes),
                    data=chunk_bytes,
                )
            )
            index += 1
        return chunks or [audio]
