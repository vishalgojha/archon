"""Vernacular pipeline: detect language, reason natively when possible, fallback safely."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from archon.vernacular.detector import DetectionResult, LanguageDetector
from archon.vernacular.reasoner import ReasoningResult, VernacularReasoner
from archon.vernacular.translator import Translator


@dataclass(slots=True, frozen=True)
class PipelineResult:
    detected_language: str
    response_language: str
    response_content: str
    method: str
    confidence: float


@dataclass(slots=True)
class _CacheRow:
    detection: DetectionResult
    expires_at: float


class VernacularPipeline:
    """High-level orchestration for language-aware responses."""

    def __init__(
        self,
        detector: LanguageDetector | None = None,
        reasoner: VernacularReasoner | None = None,
        translator: Translator | None = None,
        *,
        detection_ttl_seconds: int = 300,
    ) -> None:
        self.detector = detector or LanguageDetector()
        self.reasoner = reasoner or VernacularReasoner()
        self.translator = translator or self.reasoner.translator
        self.detection_ttl_seconds = max(1, int(detection_ttl_seconds))
        self._detection_cache: dict[str, _CacheRow] = {}

    def process(self, user_input: str, force_language: str | None = None) -> PipelineResult:
        payload = (user_input or "").strip()
        if not payload:
            return PipelineResult(
                detected_language="unknown",
                response_language="en",
                response_content="",
                method="translation_fallback",
                confidence=0.0,
            )

        detected = self._detect_with_cache(payload)
        response_language = self._normalize_code(force_language) if force_language else detected.language_code
        if not response_language or response_language == "unknown":
            response_language = "en"

        if self.reasoner.supports_native_reasoning(response_language):
            reasoning = self.reasoner.reason(payload, response_language, context={"detected_language": detected.language_code})
            method = "native_reasoning" if response_language == detected.language_code else "translated_reasoning"
            return PipelineResult(
                detected_language=detected.language_code,
                response_language=reasoning.language_code,
                response_content=reasoning.content,
                method=method,
                confidence=round(min(1.0, reasoning.confidence), 3),
            )

        fallback = self.reasoner.reason(payload, "en", context={"detected_language": detected.language_code})
        content = fallback.content
        if response_language != "en":
            translated = self.translator.translate(fallback.content, "en", response_language)
            content = translated.text

        return PipelineResult(
            detected_language=detected.language_code,
            response_language=response_language,
            response_content=content,
            method="translation_fallback",
            confidence=round(min(0.79, fallback.confidence), 3),
        )

    def _detect_with_cache(self, text: str) -> DetectionResult:
        now = time.time()
        cache_key = hashlib.sha256(text[:100].encode("utf-8", errors="ignore")).hexdigest()
        cached = self._detection_cache.get(cache_key)
        if cached and cached.expires_at > now:
            return cached.detection

        detection = self.detector.detect(text)
        self._detection_cache[cache_key] = _CacheRow(
            detection=detection,
            expires_at=now + self.detection_ttl_seconds,
        )
        self._prune_cache(now)
        return detection

    def _prune_cache(self, now: float) -> None:
        stale_keys = [key for key, row in self._detection_cache.items() if row.expires_at <= now]
        for key in stale_keys:
            self._detection_cache.pop(key, None)

    @staticmethod
    def _normalize_code(raw: str | None) -> str:
        text = (raw or "").strip().lower().replace("_", "-")
        return text.split("-", 1)[0] if text else ""
