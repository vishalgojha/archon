"""Contract tests for vernacular detection, reasoning, translation, and pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import archon.vernacular.detector as detector_mod
from archon.vernacular.detector import SUPPORTED_LANGUAGES, DetectionResult, LanguageDetector
from archon.vernacular.pipeline import VernacularPipeline
from archon.vernacular.reasoner import (
    CULTURAL_PROFILES,
    VALID_FORMALITY,
    ReasoningResult,
    VernacularReasoner,
)
from archon.vernacular.translator import TranslationResult, Translator


@dataclass(slots=True)
class _FakeLangProb:
    lang: str
    prob: float


class _FakeRouter:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.calls = 0

    async def invoke(self, *, role: str, prompt: str, system_prompt: str | None = None):  # type: ignore[no-untyped-def]
        del role, prompt, system_prompt
        self.calls += 1

        @dataclass(slots=True)
        class _Response:
            text: str

        return _Response(text=self.text)


class _FailingRouter:
    async def invoke(self, *, role: str, prompt: str, system_prompt: str | None = None):  # type: ignore[no-untyped-def]
        del role, prompt, system_prompt
        raise RuntimeError("router unavailable")


def test_language_detector_english_detected_from_langdetect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        detector_mod, "_langdetect_detect_langs", lambda _text: [_FakeLangProb("en", 0.98)]
    )

    detector = LanguageDetector(router=None)
    result = detector.detect(
        "This is an example sentence with enough words for language detection."
    )

    assert result.language_code == "en"
    assert result.script == "latin"
    assert result.confidence >= 0.9
    assert result.is_certain is True


def test_language_detector_llm_fallback_when_langdetect_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(detector_mod, "_langdetect_detect_langs", None)
    router = _FakeRouter(text='{"language_code":"es","confidence":0.92}')
    detector = LanguageDetector(router=router)

    result = detector.detect(
        "Este texto usa palabras en español para comprobar detección alternativa."
    )

    assert router.calls == 1
    assert result.language_code == "es"
    assert result.confidence == 0.92


def test_language_detector_short_text_uncertain_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        detector_mod, "_langdetect_detect_langs", lambda _text: [_FakeLangProb("en", 0.99)]
    )
    detector = LanguageDetector()

    result = detector.detect("hello")

    assert result.uncertain is True
    assert result.is_certain is False
    assert result.confidence <= 0.84


def test_language_detector_detect_batch_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        detector_mod, "_langdetect_detect_langs", lambda _text: [_FakeLangProb("en", 0.91)]
    )
    detector = LanguageDetector()

    rows = detector.detect_batch(["One", "Two", "Three"])

    assert len(rows) == 3
    assert all(isinstance(item, DetectionResult) for item in rows)


def test_supported_languages_contains_40_plus_native_names() -> None:
    assert len(SUPPORTED_LANGUAGES) >= 40
    assert all(isinstance(code, str) and len(code) == 2 for code in SUPPORTED_LANGUAGES)
    assert all(isinstance(name, str) and name.strip() for name in SUPPORTED_LANGUAGES.values())


def test_cultural_profiles_top_10_presence_and_valid_formality() -> None:
    for code in ["en", "es", "fr", "de", "ja", "zh", "ar", "hi", "pt", "ru"]:
        assert code in CULTURAL_PROFILES
        assert CULTURAL_PROFILES[code].formality in VALID_FORMALITY


def test_reasoner_system_prompt_includes_target_language_name() -> None:
    reasoner = VernacularReasoner(router=None)

    prompt = reasoner.build_system_prompt("ja")

    assert "日本語" in prompt
    assert "ja" in prompt


def test_reasoner_cultural_adaptation_changes_prompt_for_formal_languages() -> None:
    reasoner = VernacularReasoner(router=None)
    base = "Prepare a customer onboarding timeline."

    adapted_ja = reasoner.adapt_prompt(base, "ja")
    adapted_de = reasoner.adapt_prompt(base, "de")

    assert adapted_ja != base
    assert adapted_de != base
    assert "formal" in adapted_ja.lower()
    assert "formal" in adapted_de.lower()


def test_reasoner_falls_back_gracefully_when_llm_unavailable() -> None:
    reasoner = VernacularReasoner(
        router=_FailingRouter(),
        translator=Translator(router=None),
        native_supported_languages={"de", "en"},
    )

    result = reasoner.reason("Draft a rollout checklist.", "de", context={"audience": "operations"})

    assert result.language_code == "de"
    assert isinstance(result.content, str)
    assert result.content.strip()
    assert 0.0 <= result.confidence <= 1.0


def test_translator_translate_and_passthrough_and_back_verify() -> None:
    router = _FakeRouter(text="Hola mundo")
    translator = Translator(router=router)

    translated = translator.translate("Hello world", "en", "es")
    passthrough = translator.translate("Hello world", "en", "en")
    verify = translator.back_translate_verify("hello world", "en", "en")

    assert isinstance(translated, TranslationResult)
    assert translated.source == "en"
    assert translated.target == "es"
    assert translated.method == "llm"
    assert translated.text == "Hola mundo"

    assert passthrough.method == "passthrough"
    assert passthrough.text == "Hello world"

    assert verify.similarity == 1.0


class _CountingDetector:
    def __init__(self, language_code: str = "en") -> None:
        self.language_code = language_code
        self.calls = 0

    def detect(self, text: str) -> DetectionResult:
        del text
        self.calls += 1
        script = "latin" if self.language_code in {"en", "es", "fr", "de", "pt"} else "unknown"
        return DetectionResult(
            language_code=self.language_code, confidence=0.93, script=script, uncertain=False
        )


class _StubReasoner:
    def __init__(self, *, native_languages: set[str], content: str = "Stub reasoning") -> None:
        self.native_languages = native_languages
        self.content = content

    def supports_native_reasoning(self, language_code: str) -> bool:
        return language_code in self.native_languages

    def reason(self, prompt: str, language_code: str, context=None) -> ReasoningResult:  # type: ignore[no-untyped-def]
        del context
        return ReasoningResult(
            content=f"{self.content}: {prompt}", language_code=language_code, confidence=0.9
        )


class _StubTranslator:
    def __init__(self, text: str = "Translated") -> None:
        self.text = text

    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        return TranslationResult(
            text=f"{self.text} ({target_lang})",
            source=source_lang,
            target=target_lang,
            method="llm",
        )


def test_pipeline_native_reasoning_path_when_supported() -> None:
    detector = _CountingDetector(language_code="en")
    reasoner = _StubReasoner(native_languages={"en"}, content="Native")
    translator = _StubTranslator()
    pipeline = VernacularPipeline(detector=detector, reasoner=reasoner, translator=translator)

    result = pipeline.process("Provide an action plan for customer success.")

    assert result.method == "native_reasoning"
    assert result.response_language == "en"
    assert result.response_content.startswith("Native")


def test_pipeline_translation_fallback_when_native_not_supported() -> None:
    detector = _CountingDetector(language_code="ka")
    reasoner = _StubReasoner(native_languages={"en"}, content="English")
    translator = _StubTranslator(text="ქართული პასუხი")
    pipeline = VernacularPipeline(detector=detector, reasoner=reasoner, translator=translator)

    result = pipeline.process("გთხოვ დამეხმარო გეგმის შედგენაში.")

    assert result.method == "translation_fallback"
    assert result.response_language == "ka"
    assert "ქართული პასუხი" in result.response_content


def test_pipeline_cache_hit_skips_second_detection() -> None:
    detector = _CountingDetector(language_code="en")
    reasoner = _StubReasoner(native_languages={"en"}, content="Native")
    translator = _StubTranslator()
    pipeline = VernacularPipeline(detector=detector, reasoner=reasoner, translator=translator)

    text = "This sentence is intentionally long enough to avoid uncertain short-text behavior."
    first = pipeline.process(text)
    second = pipeline.process(text)

    assert first.method == "native_reasoning"
    assert second.method == "native_reasoning"
    assert detector.calls == 1
