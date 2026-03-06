"""Intent classification for crawled pages and sites."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from archon.providers import ProviderRouter
from archon.web.site_crawler import CrawlResult, PageData

IntentCategory = Literal[
    "ecommerce", "saas", "blog", "lead_gen", "portfolio", "docs", "news", "unknown"
]

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ecommerce": ("buy now", "add to cart", "checkout", "shop", "product", "price", "shipping"),
    "saas": ("free trial", "pricing", "features", "api", "dashboard", "platform", "integration"),
    "blog": ("blog", "author", "subscribe", "read more", "category", "comments"),
    "lead_gen": ("book a demo", "contact us", "get quote", "talk to sales", "request demo", "lead"),
    "portfolio": ("portfolio", "case study", "my work", "projects", "dribbble", "behance"),
    "docs": ("documentation", "getting started", "reference", "sdk", "guides", "quickstart"),
    "news": ("breaking", "latest news", "reporter", "press release", "newsroom", "updated"),
}
_VALID_CATEGORIES = set(_CATEGORY_KEYWORDS) | {"unknown"}


@dataclass(slots=True, frozen=True)
class PageIntent:
    """Intent classification for a single page."""

    category: IntentCategory
    confidence: float
    signals: dict[str, Any]


@dataclass(slots=True)
class SiteIntent:
    """Aggregated intent classification for a crawled site."""

    primary: IntentCategory
    secondary: list[IntentCategory] = field(default_factory=list)
    page_intents: list[PageIntent] = field(default_factory=list)


class IntentClassifier:
    """Keyword-first intent classifier with optional LLM fallback."""

    def __init__(self, router: ProviderRouter | None = None, *, llm_role: str = "fast") -> None:
        self.router = router
        self.llm_role = llm_role

    async def classify_page(self, page: PageData) -> PageIntent:
        """Classify one page into a high-level intent category."""

        page_text = _page_text(page)
        score_map: dict[str, int] = {}
        signal_map: dict[str, list[str]] = {}
        for category, keywords in _CATEGORY_KEYWORDS.items():
            matches = [keyword for keyword in keywords if keyword in page_text]
            if matches:
                score_map[category] = len(matches)
                signal_map[category] = matches

        if not score_map:
            return PageIntent(
                category="unknown", confidence=0.15, signals={"reason": "no_keyword_signals"}
            )

        ranked = sorted(score_map.items(), key=lambda row: row[1], reverse=True)
        top_category, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0
        ambiguous = (top_score - second_score) <= 1 and len(ranked) > 1

        if ambiguous and self.router is not None:
            llm_result = await self._classify_with_llm(page, score_map, signal_map)
            if llm_result is not None:
                return llm_result

        if ambiguous:
            return PageIntent(
                category="unknown",
                confidence=0.35,
                signals={
                    "reason": "ambiguous_keyword_signals",
                    "scores": score_map,
                    "matches": signal_map,
                },
            )

        confidence = min(0.98, 0.45 + (top_score * 0.12))
        return PageIntent(
            category=top_category,  # type: ignore[arg-type]
            confidence=round(confidence, 3),
            signals={"scores": score_map, "matches": signal_map},
        )

    async def classify_site(self, crawl_result: CrawlResult) -> SiteIntent:
        """Classify a full site from multiple page-level signals."""

        page_intents: list[PageIntent] = []
        for page in crawl_result.pages:
            page_intents.append(await self.classify_page(page))

        counter: Counter[str] = Counter(
            intent.category for intent in page_intents if intent.category != "unknown"
        )
        if not counter:
            return SiteIntent(primary="unknown", secondary=[], page_intents=page_intents)

        ranked = counter.most_common()
        primary = ranked[0][0]
        secondary: list[IntentCategory] = [
            category  # type: ignore[list-item]
            for category, _count in ranked[1:3]
            if category in _VALID_CATEGORIES and category != primary
        ]
        return SiteIntent(primary=primary, secondary=secondary, page_intents=page_intents)  # type: ignore[arg-type]

    async def _classify_with_llm(
        self,
        page: PageData,
        score_map: dict[str, int],
        signal_map: dict[str, list[str]],
    ) -> PageIntent | None:
        prompt = (
            "Classify this page into one category: ecommerce, saas, blog, lead_gen, portfolio, docs, news, unknown.\n"
            "Return JSON only with keys: category, confidence, signals.\n"
            f"URL: {page.url}\n"
            f"TITLE: {page.title}\n"
            f"H1: {page.h1s}\n"
            f"META: {page.meta_description}\n"
            f"TEXT: {page.text_content[:1500]}\n"
            f"KEYWORD_SCORES: {json.dumps(score_map)}\n"
            f"KEYWORD_MATCHES: {json.dumps(signal_map)}"
        )
        try:
            response = await self.router.invoke(role=self.llm_role, prompt=prompt)  # type: ignore[union-attr]
            parsed = _extract_json_object(response.text)
            if not parsed:
                return None
            category = str(parsed.get("category", "unknown")).lower()
            if category not in _VALID_CATEGORIES:
                category = "unknown"
            confidence = _clamp_confidence(parsed.get("confidence", 0.5))
            signals = parsed.get("signals")
            if not isinstance(signals, dict):
                signals = {"llm": parsed.get("reason", "ambiguous")}
            return PageIntent(category=category, confidence=confidence, signals=signals)  # type: ignore[arg-type]
        except Exception:
            return None


def _page_text(page: PageData) -> str:
    text = " ".join(
        [
            page.url,
            page.title,
            page.meta_description,
            " ".join(page.h1s),
            page.text_content[:4000],
        ]
    )
    return " ".join(text.lower().split())


def _extract_json_object(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(candidate[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _clamp_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.5
    return round(max(0.0, min(1.0, parsed)), 3)
