"""Vernacular language utilities for voice outreach."""

from __future__ import annotations

from typing import Callable


class VernacularAdapter:
    """Language adapter for detection and script translation.

    Uses `langdetect` when installed; otherwise falls back to an LLM-backed hook.
    Underlying LLM routes can support 40+ languages.
    """

    def __init__(
        self,
        *,
        detect_fn: Callable[[str], str] | None = None,
        translate_fn: Callable[[str, str], str] | None = None,
    ) -> None:
        """Create adapter. Example: `VernacularAdapter()`."""

        self._detect_fn = detect_fn
        self._translate_fn = translate_fn

    def detect_language(self, text: str) -> str:
        """Detect ISO language code.

        Example: `VernacularAdapter().detect_language("Hello world")`.
        """

        cleaned = str(text).strip()
        if not cleaned:
            return "und"
        try:
            from langdetect import detect  # type: ignore[import-not-found]

            code = str(detect(cleaned)).strip().lower()
            return normalize_language_code(code)
        except Exception:
            return normalize_language_code(self._llm_detect(cleaned))

    def translate_script(self, script: str, target_language: str) -> str:
        """Translate plain script text for TwiML `<Say>`.

        Example: `adapter.translate_script("Hi", "es")`.
        """

        source = str(script).strip()
        target = normalize_language_code(target_language)
        if not source:
            return ""
        if target in {"en", "und"}:
            return source
        translated = str(self._llm_translate(source, target)).strip()
        return translated or source

    def _llm_detect(self, text: str) -> str:
        if self._detect_fn is not None:
            return self._detect_fn(text)
        return "en"

    def _llm_translate(self, script: str, target_language: str) -> str:
        if self._translate_fn is not None:
            return self._translate_fn(script, target_language)
        return f"[{target_language}] {script}"


def normalize_language_code(code: str) -> str:
    """Normalize language code values.

    Example: `normalize_language_code("EN-us")`.
    """

    cleaned = str(code).strip().lower()
    return cleaned[:5] if cleaned else "und"


__all__ = ["VernacularAdapter", "normalize_language_code"]
