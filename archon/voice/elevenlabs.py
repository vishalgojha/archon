"""ElevenLabs voice integration for Archon.

Provides text-to-speech and speech-to-text capabilities using ElevenLabs API.
Supports 33M+ token quota management and voice selection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# Available ElevenLabs voices
VOICES = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",      # Warm, professional
    "domi": "AZnzlk1XvdvUeBnXmlld",        # Strong, confident
    "bella": "EXAVITQu4vr4xnSDxMaL",        # Soft, pleasant
    "antoni": "ErXwobaYiN019PkySvjV",       # Well-rounded
    "clyde": "MF3mGyEYCl7XYWbV9V6O",        # Echoing
    "elli": "TxGEqnHWrfWFTfGW9XjX",        # Expressive
    "josh": "TxGEqnHWrfWFTfGW9XjX",        # Young, natural
    "arnold": "VR6AewLTigWG4xSOukaG",       # Crisp, authoritative
    "adam": "pNInz6obpgDQGcFmaJgB",         # Deep, natural
    "sam": "onwK4e9ZLuTAKqWW03F9",          # Raspy, natural
    # Hindi voices
    "hindi_female": "pNInz6obpgDQGcFmaJgB",  # Hindi female
    "hindi_male": "onwK4e9ZLuTAKqWW03F9",    # Hindi male
}

# Default model for TTS
DEFAULT_MODEL = "eleven_multilingual_v2"


@dataclass
class VoiceConfig:
    """Configuration for voice synthesis."""
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel
    model: str = DEFAULT_MODEL
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    use_speaker_boost: bool = True


@dataclass
class ElevenLabsConfig:
    """ElevenLabs API configuration."""
    api_key: str = ""
    base_url: str = "https://api.elevenlabs.io/v1"
    voice: VoiceConfig = field(default_factory=VoiceConfig)

    @classmethod
    def from_env(cls) -> "ElevenLabsConfig":
        """Load config from environment variables."""
        return cls(
            api_key=os.environ.get("ELEVENLABS_API_KEY", ""),
            voice=VoiceConfig(
                voice_id=os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
            ),
        )


class ElevenLabsClient:
    """ElevenLabs API client for text-to-speech."""

    def __init__(self, config: ElevenLabsConfig | None = None) -> None:
        self.config = config or ElevenLabsConfig.from_env()
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            headers={"xi-api-key": self.config.api_key},
            timeout=60.0,
        )

    async def text_to_speech(
        self,
        text: str,
        voice_id: str | None = None,
        output_path: str | None = None,
    ) -> bytes:
        """Convert text to speech audio.

        Args:
            text: Text to synthesize
            voice_id: Voice to use (defaults to config)
            output_path: Optional path to save audio file

        Returns:
            Audio bytes (MP3 format)
        """
        vid = voice_id or self.config.voice.voice_id

        payload = {
            "text": text,
            "model_id": self.config.voice.model,
            "voice_settings": {
                "stability": self.config.voice.stability,
                "similarity_boost": self.config.voice.similarity_boost,
                "style": self.config.voice.style,
                "use_speaker_boost": self.config.voice.use_speaker_boost,
            },
        }

        response = await self._client.post(
            f"/text-to-speech/{vid}",
            json=payload,
        )
        response.raise_for_status()

        audio_bytes = response.content

        if output_path:
            Path(output_path).write_bytes(audio_bytes)

        return audio_bytes

    async def get_voices(self) -> list[dict[str, Any]]:
        """Get available voices."""
        response = await self._client.get("/voices")
        response.raise_for_status()
        return response.json().get("voices", [])

    async def get_usage(self) -> dict[str, Any]:
        """Get character usage statistics."""
        response = await self._client.get("/user/subscription")
        response.raise_for_status()
        return response.json()

    async def stream_speech(
        self,
        text: str,
        voice_id: str | None = None,
    ):
        """Stream text-to-speech audio.

        Yields:
            Audio chunks as bytes
        """
        vid = voice_id or self.config.voice.voice_id

        payload = {
            "text": text,
            "model_id": self.config.voice.model,
            "voice_settings": {
                "stability": self.config.voice.stability,
                "similarity_boost": self.config.voice.similarity_boost,
            },
        }

        async with self._client.stream(
            "POST",
            f"/text-to-speech/{vid}/stream",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes(chunk_size=1024):
                yield chunk

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()


class VoiceAssistant:
    """High-level voice assistant for Archon."""

    def __init__(self, config: ElevenLabsConfig | None = None) -> None:
        self.config = config or ElevenLabsConfig.from_env()
        self.client = ElevenLabsClient(self.config)
        self._enabled = bool(self.config.api_key)

    @property
    def enabled(self) -> bool:
        """Check if voice assistant is configured."""
        return self._enabled

    async def speak(self, text: str, save_to: str | None = None) -> str | None:
        """Convert text to speech and optionally save to file.

        Args:
            text: Text to speak
            save_to: Optional file path to save audio

        Returns:
            Path to saved audio file, or None
        """
        if not self._enabled:
            return None

        output = save_to or "archon_response.mp3"
        await self.client.text_to_speech(text, output_path=output)
        return output

    async def get_status(self) -> dict[str, Any]:
        """Get voice assistant status and quota info."""
        if not self._enabled:
            return {"enabled": False, "reason": "No API key configured"}

        try:
            usage = await self.client.get_usage()
            return {
                "enabled": True,
                "character_limit": usage.get("character_limit", 0),
                "characters_used": usage.get("characters_used", 0),
                "characters_remaining": usage.get("character_limit", 0) - usage.get("characters_used", 0),
                "next_reset": usage.get("next_character_count_reset_unix"),
            }
        except Exception as e:
            return {"enabled": True, "error": str(e)}

    async def aclose(self) -> None:
        """Close resources."""
        await self.client.aclose()
