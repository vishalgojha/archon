"""Real-time translation streaming primitives for tokenized outputs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, Iterable
from dataclasses import dataclass
from typing import Callable

from archon.vernacular.detector import LanguageDetector
from archon.vernacular.translator import Translator


@dataclass(slots=True, frozen=True)
class TranslatedToken:
    """Translated stream chunk metadata."""

    content: str
    source_lang: str
    target_lang: str
    was_translated: bool
    buffer_flush_reason: str


class TranslationBuffer:
    """Character buffer that flushes on sentence boundary or size threshold."""

    def __init__(self, max_size: int = 200, flush_on: set[str] | None = None) -> None:
        self.max_size = max(1, int(max_size))
        self.flush_on = set(flush_on or {".", "!", "?", "。", "।", "؟", "\n"})
        self._buffer: list[str] = []

    def add(self, text: str) -> list[tuple[str, str]]:
        """Append content and return any flushed segments."""

        flushed: list[tuple[str, str]] = []
        for char in str(text):
            self._buffer.append(char)
            if char in self.flush_on:
                row = self.flush("boundary")
                if row is not None:
                    flushed.append(row)
                continue
            if self.size >= self.max_size:
                row = self.flush("max_size")
                if row is not None:
                    flushed.append(row)
        return flushed

    @property
    def size(self) -> int:
        return len(self._buffer)

    def flush(self, reason: str) -> tuple[str, str] | None:
        if not self._buffer:
            return None
        payload = "".join(self._buffer)
        self._buffer = []
        return payload, str(reason)


class StreamingTranslator:
    """Streams translated chunks while preserving boundary-aware buffering."""

    def __init__(
        self,
        translator: Translator | None = None,
        detector: LanguageDetector | None = None,
        *,
        max_buffer_size: int = 200,
        flush_on: set[str] | None = None,
        default_source_lang: str = "en",
        default_target_lang: str = "en",
        detect_language_fn: Callable[[str], str] | None = None,
        translate_text_fn: Callable[[str, str, str], str] | None = None,
    ) -> None:
        self.translator = translator or Translator(router=None)
        self.detector = detector or LanguageDetector(router=None)
        self.max_buffer_size = max(1, int(max_buffer_size))
        self.flush_on = set(flush_on or {".", "!", "?", "。", "।", "؟", "\n"})
        self.default_source_lang = _normalize_lang(default_source_lang)
        self.default_target_lang = _normalize_lang(default_target_lang)
        self.detect_language_fn = detect_language_fn
        self.translate_text_fn = translate_text_fn
        self._language_pair_cache: dict[tuple[str, str], bool] = {}

    async def stream_translate(
        self,
        token_generator: AsyncIterable[str] | Iterable[str],
        source_lang: str,
        target_lang: str,
    ) -> AsyncGenerator[str]:
        """Translate stream chunks and yield translated content only."""

        async for _original, token in self.stream_translate_with_metadata(
            token_generator,
            source_lang=source_lang,
            target_lang=target_lang,
        ):
            yield token.content

    async def stream_translate_with_metadata(
        self,
        token_generator: AsyncIterable[str] | Iterable[str],
        source_lang: str,
        target_lang: str,
    ) -> AsyncGenerator[tuple[str, TranslatedToken]]:
        """Translate stream chunks and include original chunk metadata."""

        source = _normalize_lang(source_lang)
        target = _normalize_lang(target_lang)
        buffer = TranslationBuffer(max_size=self.max_buffer_size, flush_on=self.flush_on)

        async for token in _iterate_tokens(token_generator):
            for original, reason in buffer.add(token):
                translated, was_translated = await self._translate_chunk(original, source, target)
                yield (
                    original,
                    TranslatedToken(
                        content=translated,
                        source_lang=source,
                        target_lang=target,
                        was_translated=was_translated,
                        buffer_flush_reason=reason,
                    ),
                )

        remainder = buffer.flush("stream_end")
        if remainder is not None:
            original, reason = remainder
            translated, was_translated = await self._translate_chunk(original, source, target)
            yield (
                original,
                TranslatedToken(
                    content=translated,
                    source_lang=source,
                    target_lang=target,
                    was_translated=was_translated,
                    buffer_flush_reason=reason,
                ),
            )

    async def stream_detect_and_translate(
        self,
        token_generator: AsyncIterable[str] | Iterable[str],
    ) -> AsyncGenerator[TranslatedToken]:
        """Detect target language from first 100 chars, then stream translation."""

        iterator = _iterate_tokens(token_generator)
        sampled_chars = ""
        buffered_tokens: list[str] = []

        while len(sampled_chars) < 100:
            try:
                token = await anext(iterator)
            except StopAsyncIteration:
                break
            buffered_tokens.append(token)
            sampled_chars += token

        detected_target = await self._detect_language(sampled_chars[:100])

        async def replay_stream() -> AsyncGenerator[str]:
            for item in buffered_tokens:
                yield item
            async for item in iterator:
                yield item

        async for _original, token in self.stream_translate_with_metadata(
            replay_stream(),
            source_lang=self.default_source_lang,
            target_lang=detected_target,
        ):
            yield token

    async def _detect_language(self, sample: str) -> str:
        if not sample.strip():
            return self.default_target_lang

        if callable(self.detect_language_fn):
            value = self.detect_language_fn(sample)
            if asyncio.iscoroutine(value):
                value = await value
            return _normalize_lang(str(value or self.default_target_lang))

        detection = await asyncio.to_thread(self.detector.detect, sample)
        code = _normalize_lang(str(getattr(detection, "language_code", "") or ""))
        return code or self.default_target_lang

    async def _translate_chunk(
        self, text: str, source_lang: str, target_lang: str
    ) -> tuple[str, bool]:
        pair = (source_lang, target_lang)
        if pair in self._language_pair_cache and self._language_pair_cache[pair]:
            return text, False
        if source_lang == target_lang:
            self._language_pair_cache[pair] = True
            return text, False

        if callable(self.translate_text_fn):
            translated = self.translate_text_fn(text, source_lang, target_lang)
            if asyncio.iscoroutine(translated):
                translated = await translated
            normalized = str(translated)
            return normalized, True

        translated_result = await asyncio.to_thread(
            self.translator.translate,
            text,
            source_lang,
            target_lang,
        )
        translated_text = str(getattr(translated_result, "text", "") or text)
        return translated_text, True


async def _iterate_tokens(
    token_generator: AsyncIterable[str] | Iterable[str],
) -> AsyncGenerator[str]:
    if hasattr(token_generator, "__aiter__"):
        async for token in token_generator:  # type: ignore[union-attr]
            yield str(token)
        return

    for token in token_generator:  # type: ignore[union-attr]
        yield str(token)


def _normalize_lang(raw: str) -> str:
    value = str(raw or "").strip().lower().replace("_", "-")
    if not value:
        return "unknown"
    return value.split("-", 1)[0]
