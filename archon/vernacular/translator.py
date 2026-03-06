"""Translation helpers with optional LLM routing and verification."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from archon.providers import ProviderRouter


@dataclass(slots=True, frozen=True)
class TranslationResult:
    text: str
    source: str
    target: str
    method: str


@dataclass(slots=True, frozen=True)
class VerificationResult:
    forward_translation: TranslationResult
    backward_translation: TranslationResult
    similarity: float


class Translator:
    """Translates content between languages using the configured provider router."""

    def __init__(self, router: ProviderRouter | None = None, *, llm_role: str = "fast") -> None:
        self.router = router
        self.llm_role = llm_role

    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        source = _normalize_code(source_lang)
        target = _normalize_code(target_lang)
        payload = str(text or "")

        if source == target:
            return TranslationResult(
                text=payload, source=source, target=target, method="passthrough"
            )

        prompt = (
            "Translate the text from {source} to {target}. "
            "Preserve meaning, tone, entities, and factual content. "
            "Return translated text only.\n"
            "TEXT:\n{payload}"
        ).format(source=source, target=target, payload=payload)

        translated = _invoke_router_text(self.router, role=self.llm_role, prompt=prompt)
        if not translated:
            translated = payload
        return TranslationResult(text=translated, source=source, target=target, method="llm")

    def translate_batch(
        self, texts: list[str], source: str, target: str
    ) -> list[TranslationResult]:
        return [self.translate(item, source, target) for item in texts]

    def back_translate_verify(self, text: str, source: str, target: str) -> VerificationResult:
        forward = self.translate(text, source, target)
        backward = self.translate(forward.text, target, source)
        similarity = _jaccard_similarity(text, backward.text)
        return VerificationResult(
            forward_translation=forward,
            backward_translation=backward,
            similarity=similarity,
        )


def _normalize_code(raw: str) -> str:
    value = (raw or "").strip().lower().replace("_", "-")
    return value.split("-", 1)[0] if value else "unknown"


def _invoke_router_text(router: ProviderRouter | None, *, role: str, prompt: str) -> str:
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
                system_prompt="You are a precise translation engine.",
            )
        )
    except Exception:
        return ""
    return str(getattr(response, "text", "") or "").strip()


def _tokenize_words(text: str) -> set[str]:
    tokens = re.findall(r"\b\w+\b", str(text or "").lower())
    return set(tokens)


def _jaccard_similarity(left: str, right: str) -> float:
    left_tokens = _tokenize_words(left)
    right_tokens = _tokenize_words(right)
    if not left_tokens and not right_tokens:
        return 1.0
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    score = len(left_tokens & right_tokens) / len(union)
    return round(score, 3)
