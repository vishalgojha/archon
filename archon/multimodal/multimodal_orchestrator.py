"""Multimodal orchestration pipeline for text, image, and audio inputs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from archon.config import ArchonConfig
from archon.core.orchestrator import Orchestrator
from archon.multimodal.audio_input import AudioInput, AudioProcessor, TranscriptResult
from archon.multimodal.image_input import ImageInput, ImageProcessor
from archon.providers.router import ProviderSelection, ProviderUnavailableError

VISION_CAPABLE_PROVIDERS = ["anthropic", "openai", "gemini"]


@dataclass(slots=True)
class MultimodalResponse:
    """Normalized multimodal response payload.

    Example:
        >>> MultimodalResponse(content="ok", provider="openai", model="gpt-4o").provider
        'openai'
    """

    content: str
    provider: str
    model: str
    transcript: str = ""
    structured_data: list[dict[str, Any] | str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class MultimodalOrchestrator(Orchestrator):
    """Extend the base orchestrator with mixed image and audio input handling.

    Example:
        >>> orchestrator = MultimodalOrchestrator(ArchonConfig())
        >>> hasattr(orchestrator, "process")
        True
    """

    def __init__(
        self,
        config: ArchonConfig,
        live_provider_calls: bool = False,
        *,
        image_processor: ImageProcessor | None = None,
        audio_processor: AudioProcessor | None = None,
    ) -> None:
        super().__init__(config=config, live_provider_calls=live_provider_calls)
        self.image_processor = image_processor or ImageProcessor()
        self.audio_processor = audio_processor or AudioProcessor()

    async def process(
        self,
        *,
        text: str | None = None,
        images: list[ImageInput | bytes | str] | None = None,
        audio: list[AudioInput | bytes] | None = None,
        session_id: str,
        tenant_ctx: dict[str, Any],
    ) -> MultimodalResponse:
        """Process text, image, and audio inputs through a vision-capable provider.

        Example:
            >>> orchestrator = MultimodalOrchestrator(ArchonConfig())
            >>> hasattr(orchestrator, "process")
            True
        """

        task_id = f"multimodal-{session_id}"
        self.cost_governor.start_task(task_id)

        prompt_text = str(text or "").strip()
        transcripts: list[TranscriptResult] = []
        for item in audio or []:
            loaded_audio = item if isinstance(item, AudioInput) else self.audio_processor.load_from_bytes(item)
            transcript = (
                await self.audio_processor.transcribe_long(loaded_audio)
                if loaded_audio.duration_s > 30
                else await self.audio_processor.transcribe(loaded_audio)
            )
            transcripts.append(transcript)
            if transcript.text.strip():
                prompt_text = "\n".join(part for part in [prompt_text, transcript.text.strip()] if part)

        loaded_images: list[ImageInput] = []
        for item in images or []:
            if isinstance(item, ImageInput):
                image = item
            elif isinstance(item, bytes):
                image = self.image_processor.load_from_bytes(item)
            elif isinstance(item, str):
                image = await self.image_processor.load_from_url(item)
            else:
                raise TypeError("images must contain ImageInput, bytes, or URL strings.")
            loaded_images.append(self.image_processor.resize_if_needed(image))

        structured_payloads: list[dict[str, Any] | str] = []
        for image in loaded_images:
            if await self.detect_structured_data(image, session_id=session_id, tenant_ctx=tenant_ctx):
                extracted = await self.extract_structured_data(
                    image,
                    session_id=session_id,
                    tenant_ctx=tenant_ctx,
                )
                structured_payloads.append(extracted)
                prompt_text = "\n".join(
                    part
                    for part in [
                        prompt_text,
                        "Structured extraction:",
                        extracted if isinstance(extracted, str) else json.dumps(extracted, separators=(",", ":")),
                    ]
                    if part
                )

        selection = self._select_vision_provider()
        response = await self.provider_router.invoke_multimodal(
            role="vision",
            text=prompt_text or "Analyze the provided multimodal inputs.",
            content_blocks=[self.image_processor.to_llm_content(image) for image in loaded_images],
            task_id=task_id,
            provider_override=selection.provider,
        )
        return MultimodalResponse(
            content=response.text,
            provider=response.provider,
            model=response.model,
            transcript=" ".join(item.text for item in transcripts if item.text).strip(),
            structured_data=structured_payloads,
            metadata={
                "session_id": session_id,
                "tenant_ctx": dict(tenant_ctx),
                "image_count": len(loaded_images),
                "audio_count": len(audio or []),
            },
        )

    async def detect_structured_data(
        self,
        image: ImageInput,
        *,
        session_id: str,
        tenant_ctx: dict[str, Any],
    ) -> bool:
        """Heuristically detect whether an image likely contains structured data.

        Example:
            >>> orchestrator = MultimodalOrchestrator(ArchonConfig())
            >>> __import__("asyncio").run(orchestrator.detect_structured_data(ImageInput("img", "upload", "jpeg", 10, 10, 3, "YWJj"), session_id="s1", tenant_ctx={}))
            False
        """

        del session_id, tenant_ctx
        return image.source in {"screenshot", "clipboard"} or (
            image.width >= 1200 and image.height >= 800
        )

    async def extract_structured_data(
        self,
        image: ImageInput,
        *,
        session_id: str,
        tenant_ctx: dict[str, Any],
    ) -> dict[str, Any] | str:
        """Extract structured content from an image with the vision router.

        Example:
            >>> orchestrator = MultimodalOrchestrator(ArchonConfig())
            >>> hasattr(orchestrator, "extract_structured_data")
            True
        """

        del session_id, tenant_ctx
        response = await self.provider_router.invoke_multimodal(
            role="vision",
            text="Extract any table, form, or chart data from this image as compact JSON.",
            content_blocks=[self.image_processor.to_llm_content(image)],
        )
        try:
            parsed = json.loads(response.text)
        except json.JSONDecodeError:
            return response.text
        return parsed if isinstance(parsed, dict) else response.text

    def _select_vision_provider(self) -> ProviderSelection:
        candidates: list[str] = []
        for provider in [
            self.config.byok.vision,
            self.config.byok.primary,
            self.config.byok.fallback,
            *VISION_CAPABLE_PROVIDERS,
        ]:
            normalized = str(provider or "").strip().lower()
            if normalized in VISION_CAPABLE_PROVIDERS and normalized not in candidates:
                candidates.append(normalized)
        for provider in candidates:
            try:
                selection = self.provider_router.resolve_provider("vision", provider_override=provider)
            except ProviderUnavailableError:
                continue
            if selection.provider in VISION_CAPABLE_PROVIDERS:
                return selection
        raise ProviderUnavailableError(
            "No configured vision-capable provider available. Supported providers: anthropic, openai, gemini."
        )
