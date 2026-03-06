"""Language detection with script awareness and LLM fallback."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from archon.providers import ProviderRouter

try:
    from langdetect import detect_langs as _langdetect_detect_langs
except Exception:  # pragma: no cover - optional dependency
    _langdetect_detect_langs = None

SUPPORTED_LANGUAGES: dict[str, str] = {
    "af": "Afrikaans",
    "ar": "العربية",
    "az": "Azərbaycanca",
    "be": "Беларуская",
    "bg": "Български",
    "bn": "বাংলা",
    "ca": "Català",
    "cs": "Čeština",
    "da": "Dansk",
    "de": "Deutsch",
    "el": "Ελληνικά",
    "en": "English",
    "es": "Español",
    "et": "Eesti",
    "fa": "فارسی",
    "fi": "Suomi",
    "fr": "Français",
    "ga": "Gaeilge",
    "gu": "ગુજરાતી",
    "he": "עברית",
    "hi": "हिन्दी",
    "hr": "Hrvatski",
    "hu": "Magyar",
    "hy": "Հայերեն",
    "id": "Bahasa Indonesia",
    "it": "Italiano",
    "ja": "日本語",
    "ka": "ქართული",
    "kn": "ಕನ್ನಡ",
    "ko": "한국어",
    "lt": "Lietuvių",
    "lv": "Latviešu",
    "mk": "Македонски",
    "ml": "മലയാളം",
    "mr": "मराठी",
    "ms": "Bahasa Melayu",
    "nl": "Nederlands",
    "no": "Norsk",
    "pa": "ਪੰਜਾਬੀ",
    "pl": "Polski",
    "pt": "Português",
    "ro": "Română",
    "ru": "Русский",
    "sk": "Slovenčina",
    "sl": "Slovenščina",
    "sq": "Shqip",
    "sr": "Српски",
    "sv": "Svenska",
    "sw": "Kiswahili",
    "ta": "தமிழ்",
    "te": "తెలుగు",
    "th": "ไทย",
    "tl": "Filipino",
    "tr": "Türkçe",
    "uk": "Українська",
    "ur": "اردو",
    "vi": "Tiếng Việt",
    "zh": "中文",
    "zu": "isiZulu",
}

_SCRIPT_HINT_LANGUAGE = {
    "cyrillic": "ru",
    "arabic": "ar",
    "devanagari": "hi",
    "cjk": "zh",
    "hangul": "ko",
    "hebrew": "he",
    "thai": "th",
    "georgian": "ka",
    "latin": "en",
}


@dataclass(slots=True, frozen=True)
class DetectionResult:
    """Language detection output."""

    language_code: str
    confidence: float
    script: str
    uncertain: bool = False

    @property
    def is_certain(self) -> bool:
        return self.confidence > 0.85 and not self.uncertain


class LanguageDetector:
    """Detects language codes and writing scripts with optional LLM fallback."""

    def __init__(self, router: ProviderRouter | None = None, *, llm_role: str = "fast") -> None:
        self.router = router
        self.llm_role = llm_role

    def detect(self, text: str) -> DetectionResult:
        source = (text or "").strip()
        if not source:
            return DetectionResult(language_code="unknown", confidence=0.0, script="unknown", uncertain=True)

        script = _detect_script(source)
        uncertain = len(source) < 20

        code = "unknown"
        confidence = 0.0

        if _langdetect_detect_langs is not None:
            code, confidence = self._detect_with_langdetect(source)
        else:
            code, confidence = self._detect_with_llm(source, script)

        if code not in SUPPORTED_LANGUAGES:
            code = _SCRIPT_HINT_LANGUAGE.get(script, "unknown")
            confidence = max(confidence * 0.65, 0.35 if code != "unknown" else 0.0)

        confidence = max(0.0, min(1.0, float(confidence)))
        if uncertain:
            confidence = min(confidence, 0.84)

        return DetectionResult(
            language_code=code,
            confidence=round(confidence, 3),
            script=script,
            uncertain=uncertain,
        )

    def detect_batch(self, texts: list[str]) -> list[DetectionResult]:
        return [self.detect(item) for item in texts]

    def _detect_with_langdetect(self, text: str) -> tuple[str, float]:
        try:
            ranked = _langdetect_detect_langs(text)
            if not ranked:
                return "unknown", 0.0
            best = ranked[0]
            lang = _normalize_language_code(getattr(best, "lang", "unknown"))
            confidence = float(getattr(best, "prob", 0.0))
            return lang, confidence
        except Exception:
            return self._detect_with_llm(text, _detect_script(text))

    def _detect_with_llm(self, text: str, script: str) -> tuple[str, float]:
        if self.router is None:
            return _SCRIPT_HINT_LANGUAGE.get(script, "unknown"), 0.45

        prompt = (
            "Detect the ISO-639-1 language code for this text. "
            "Return JSON only: {\"language_code\":\"xx\",\"confidence\":0.0-1.0}.\n"
            f"Text: {text[:600]}"
        )
        response_text = _invoke_router_text(self.router, role=self.llm_role, prompt=prompt)
        if not response_text:
            return _SCRIPT_HINT_LANGUAGE.get(script, "unknown"), 0.45

        parsed = _extract_json_object(response_text)
        if not parsed:
            maybe_code = _normalize_language_code(response_text)
            if maybe_code in SUPPORTED_LANGUAGES:
                return maybe_code, 0.6
            return _SCRIPT_HINT_LANGUAGE.get(script, "unknown"), 0.45

        raw_code = _normalize_language_code(str(parsed.get("language_code", "unknown")))
        if raw_code not in SUPPORTED_LANGUAGES:
            raw_code = _SCRIPT_HINT_LANGUAGE.get(script, "unknown")

        raw_confidence = parsed.get("confidence", 0.5)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = 0.5

        return raw_code, max(0.0, min(1.0, confidence))


def _normalize_language_code(raw: str) -> str:
    code = (raw or "").strip().lower().replace("_", "-")
    if not code:
        return "unknown"
    base = code.split("-", 1)[0]
    return base if re.match(r"^[a-z]{2}$", base) else "unknown"


def _invoke_router_text(router: ProviderRouter, *, role: str, prompt: str, system_prompt: str | None = None) -> str:
    try:
        asyncio.get_running_loop()
        # Called from async context without async API; avoid nested loop deadlocks.
        return ""
    except RuntimeError:
        pass

    try:
        response = asyncio.run(
            router.invoke(
                role=role,
                prompt=prompt,
                system_prompt=system_prompt,
            )
        )
    except Exception:
        return ""
    return str(getattr(response, "text", "") or "").strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    blob = (text or "").strip()
    if not blob:
        return None

    if blob.startswith("```"):
        lines = blob.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        blob = "\n".join(lines).strip()

    try:
        parsed = json.loads(blob)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = blob.find("{")
    end = blob.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(blob[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _detect_script(text: str) -> str:
    counts: dict[str, int] = {}
    for char in text:
        script = _script_for_char(char)
        if script == "unknown":
            continue
        counts[script] = counts.get(script, 0) + 1

    if not counts:
        return "unknown"
    return max(counts.items(), key=lambda row: row[1])[0]


def _script_for_char(char: str) -> str:
    code = ord(char)

    if 0x0041 <= code <= 0x024F:
        return "latin"
    if 0x0400 <= code <= 0x052F:
        return "cyrillic"
    if 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F or 0x08A0 <= code <= 0x08FF:
        return "arabic"
    if 0x0900 <= code <= 0x097F:
        return "devanagari"
    if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0x3040 <= code <= 0x30FF:
        return "cjk"
    if 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF:
        return "hangul"
    if 0x0590 <= code <= 0x05FF:
        return "hebrew"
    if 0x0E00 <= code <= 0x0E7F:
        return "thai"
    if 0x10A0 <= code <= 0x10FF or 0x2D00 <= code <= 0x2D2F:
        return "georgian"
    return "unknown"
