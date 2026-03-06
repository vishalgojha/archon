"""Native-language reasoning with cultural adaptation profiles."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from archon.providers import ProviderRouter
from archon.vernacular.detector import SUPPORTED_LANGUAGES
from archon.vernacular.translator import Translator

VALID_FORMALITY = {"formal", "neutral", "informal", "mixed"}


@dataclass(slots=True, frozen=True)
class CulturalProfile:
    language_code: str
    formality: str
    date_format: str
    currency_symbol: str
    honorific_style: str


def _build_profiles() -> dict[str, CulturalProfile]:
    defaults: dict[str, CulturalProfile] = {}
    for code in SUPPORTED_LANGUAGES:
        defaults[code] = CulturalProfile(
            language_code=code,
            formality="neutral",
            date_format="YYYY-MM-DD",
            currency_symbol="$",
            honorific_style="standard",
        )

    overrides = {
        "en": CulturalProfile("en", "neutral", "MM/DD/YYYY", "$", "minimal"),
        "es": CulturalProfile("es", "neutral", "DD/MM/YYYY", "€", "usted_tu_contextual"),
        "fr": CulturalProfile("fr", "formal", "DD/MM/YYYY", "€", "vous_default"),
        "de": CulturalProfile("de", "formal", "DD.MM.YYYY", "€", "Sie_default"),
        "ja": CulturalProfile("ja", "formal", "YYYY年MM月DD日", "¥", "keigo"),
        "zh": CulturalProfile("zh", "neutral", "YYYY年MM月DD日", "¥", "respectful"),
        "ar": CulturalProfile("ar", "formal", "DD/MM/YYYY", "د.إ", "honorific"),
        "hi": CulturalProfile("hi", "neutral", "DD-MM-YYYY", "₹", "respectful"),
        "pt": CulturalProfile("pt", "neutral", "DD/MM/YYYY", "R$", "senhor_senhora_contextual"),
        "ru": CulturalProfile("ru", "formal", "DD.MM.YYYY", "₽", "vy_formal"),
    }
    defaults.update(overrides)
    return defaults


CULTURAL_PROFILES: dict[str, CulturalProfile] = _build_profiles()


@dataclass(slots=True, frozen=True)
class ReasoningResult:
    content: str
    language_code: str
    confidence: float


class VernacularReasoner:
    """Reason directly in the target language when supported by the active LLM."""

    def __init__(
        self,
        router: ProviderRouter | None = None,
        *,
        translator: Translator | None = None,
        llm_role: str = "primary",
        native_supported_languages: set[str] | None = None,
    ) -> None:
        self.router = router
        self.translator = translator or Translator(router=router)
        self.llm_role = llm_role
        self.native_supported_languages = native_supported_languages or {
            "en",
            "es",
            "fr",
            "de",
            "pt",
            "it",
            "ja",
            "zh",
            "ko",
            "ar",
            "hi",
            "ru",
            "tr",
            "vi",
            "th",
            "id",
        }

    def supports_native_reasoning(self, language_code: str) -> bool:
        normalized = _normalize_language_code(language_code)
        return self.router is not None and normalized in self.native_supported_languages

    def build_system_prompt(self, language_code: str) -> str:
        normalized = _normalize_language_code(language_code)
        native_name = SUPPORTED_LANGUAGES.get(normalized, "English")
        profile = CULTURAL_PROFILES.get(normalized, CULTURAL_PROFILES["en"])
        return (
            "You are ARCHON reasoning engine. Think and respond natively in "
            f"{native_name} ({normalized}).\n"
            "Do not translate from English word-for-word. Use local idiom and natural sentence flow.\n"
            f"Formality: {profile.formality}. Date format: {profile.date_format}. "
            f"Currency symbol: {profile.currency_symbol}. Honorific style: {profile.honorific_style}."
        )

    def adapt_prompt(self, prompt: str, language_code: str) -> str:
        profile = CULTURAL_PROFILES.get(_normalize_language_code(language_code), CULTURAL_PROFILES["en"])
        adaptation_lines = [
            f"[Cultural profile: {profile.language_code}]",
            f"- Use {profile.formality} register.",
            f"- Prefer date format {profile.date_format}.",
            f"- Use currency symbol {profile.currency_symbol} where relevant.",
            f"- Honorific style: {profile.honorific_style}.",
        ]
        if profile.formality == "formal":
            adaptation_lines.append("- Keep tone respectful and avoid slang.")
        if profile.language_code in {"ja", "de"}:
            adaptation_lines.append("- Explicitly preserve formal wording conventions.")
        return f"{prompt.strip()}\n\n" + "\n".join(adaptation_lines)

    def reason(
        self,
        prompt: str,
        language_code: str,
        context: dict[str, Any] | None = None,
    ) -> ReasoningResult:
        raw_prompt = (prompt or "").strip()
        if not raw_prompt:
            return ReasoningResult(content="", language_code="en", confidence=0.0)

        context = context or {}
        target_code = _normalize_language_code(language_code)
        if target_code not in SUPPORTED_LANGUAGES:
            target_code = "en"

        adapted_prompt = self.adapt_prompt(raw_prompt, target_code)

        if self.supports_native_reasoning(target_code):
            system_prompt = self.build_system_prompt(target_code)
            response = _invoke_router_text(
                self.router,
                role=self.llm_role,
                prompt=_merge_context_prompt(adapted_prompt, context),
                system_prompt=system_prompt,
            )
            if response:
                return ReasoningResult(content=response, language_code=target_code, confidence=0.9)

        english_reasoning = self._reason_in_english(raw_prompt, context)
        if target_code != "en":
            translated = self.translator.translate(english_reasoning, "en", target_code)
            return ReasoningResult(
                content=translated.text,
                language_code=target_code,
                confidence=0.72 if translated.text else 0.45,
            )

        return ReasoningResult(content=english_reasoning, language_code="en", confidence=0.62)

    def _reason_in_english(self, prompt: str, context: dict[str, Any]) -> str:
        english_prompt = self.adapt_prompt(prompt, "en")
        merged = _merge_context_prompt(english_prompt, context)
        if self.router is None:
            return prompt

        response = _invoke_router_text(
            self.router,
            role=self.llm_role,
            prompt=merged,
            system_prompt=self.build_system_prompt("en"),
        )
        return response or prompt


def _normalize_language_code(raw: str) -> str:
    code = (raw or "").strip().lower().replace("_", "-")
    if not code:
        return "en"
    return code.split("-", 1)[0]


def _merge_context_prompt(prompt: str, context: dict[str, Any]) -> str:
    if not context:
        return prompt
    rows = [prompt, "\n[Context]"]
    for key in sorted(context):
        rows.append(f"- {key}: {context[key]}")
    return "\n".join(rows)


def _invoke_router_text(
    router: ProviderRouter | None,
    *,
    role: str,
    prompt: str,
    system_prompt: str | None = None,
) -> str:
    if router is None:
        return ""

    try:
        asyncio.get_running_loop()
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
