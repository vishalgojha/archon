"""Tests for web crawling, intent classification, embed generation, and optimization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from archon.web.injection_generator import InjectionGenerator
from archon.web.intent_classifier import IntentClassifier
from archon.web.optimizer_agent import OptimizerAgent
from archon.web.site_crawler import CrawlResult, PageData, SiteCrawler


@dataclass
class _FakeResponse:
    url: str
    text: str
    status_code: int = 200
    content_type: str = "text/html; charset=utf-8"

    @property
    def headers(self) -> dict[str, str]:
        return {"content-type": self.content_type}


class _FakeAsyncClient:
    last_instance: "_FakeAsyncClient | None" = None
    routes: dict[str, _FakeResponse] = {}

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        del args, kwargs
        self.requested: list[str] = []
        self.__class__.last_instance = self

    async def get(self, url: str):  # type: ignore[no-untyped-def]
        self.requested.append(url)
        return self.routes.get(url) or _FakeResponse(url=url, text="not found", status_code=404)

    async def aclose(self) -> None:
        return None


def _html(title: str, body: str, *, meta: str = "", h1: str = "") -> str:
    return (
        "<html><head>"
        f"<title>{title}</title>"
        f"<meta name='description' content='{meta}'>"
        "</head><body>"
        f"<h1>{h1}</h1>"
        f"{body}"
        "</body></html>"
    )


@pytest.mark.asyncio
async def test_site_crawler_respects_limits_dedup_domain_and_robots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import archon.web.site_crawler as crawler_module

    _FakeAsyncClient.routes = {
        "https://example.com/robots.txt": _FakeResponse(
            url="https://example.com/robots.txt",
            text="User-agent: *\nDisallow: /private\n",
            content_type="text/plain",
        ),
        "https://example.com/": _FakeResponse(
            url="https://example.com/",
            text=_html(
                "Home",
                (
                    "<a href='/about'>About</a>"
                    "<a href='/dup'>Dup1</a>"
                    "<a href='/dup'>Dup2</a>"
                    "<a href='https://other.com/page'>Offsite</a>"
                    "<a href='/private'>Private</a>"
                    "<a href='/image.png'>Image</a>"
                ),
                meta="welcome page",
                h1="Welcome",
            ),
        ),
        "https://example.com/about": _FakeResponse(
            url="https://example.com/about",
            text=_html("About", "<a href='/dup'>Dup</a>", meta="about us", h1="About"),
        ),
        "https://example.com/dup": _FakeResponse(
            url="https://example.com/dup",
            text=_html("Dup", "<p>duplicate page</p>", meta="dup", h1="Dup"),
        ),
        "https://example.com/private": _FakeResponse(
            url="https://example.com/private",
            text=_html("Private", "<p>private</p>", meta="private"),
        ),
    }
    monkeypatch.setattr(crawler_module.httpx, "AsyncClient", _FakeAsyncClient)

    crawler = SiteCrawler(max_concurrent=3, delay_between_requests_ms=0)
    try:
        result = await crawler.crawl("https://example.com/", max_pages=3, max_depth=2)
    finally:
        await crawler.aclose()

    assert isinstance(result, CrawlResult)
    assert len(result.pages) == 3
    fetched_urls = [page.url for page in result.pages]
    assert "https://example.com/" in fetched_urls
    assert "https://example.com/about" in fetched_urls
    assert "https://example.com/dup" in fetched_urls
    assert "https://example.com/private" not in fetched_urls
    assert all("other.com" not in url for url in fetched_urls)
    assert all(not url.endswith(".png") for url in fetched_urls)

    client = _FakeAsyncClient.last_instance
    assert client is not None
    assert client.requested.count("https://example.com/dup") == 1
    assert "https://example.com/private" not in client.requested


@pytest.mark.asyncio
async def test_site_crawler_crawl_single(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.web.site_crawler as crawler_module

    _FakeAsyncClient.routes = {
        "https://single.example.com/page": _FakeResponse(
            url="https://single.example.com/page",
            text=_html("Single", "<p>one page</p>", meta="single", h1="Single H1"),
        )
    }
    monkeypatch.setattr(crawler_module.httpx, "AsyncClient", _FakeAsyncClient)

    crawler = SiteCrawler(delay_between_requests_ms=0)
    try:
        page = await crawler.crawl_single("https://single.example.com/page")
    finally:
        await crawler.aclose()

    assert isinstance(page, PageData)
    assert page.title == "Single"
    assert page.meta_description == "single"
    assert page.h1s == ["Single H1"]
    assert "one page" in page.text_content


def _page(url: str, title: str, text: str, meta: str = "", h1s: list[str] | None = None) -> PageData:
    return PageData(
        url=url,
        title=title,
        text_content=text,
        meta_description=meta,
        h1s=h1s or [],
        links=[],
        load_ms=12.0,
    )


@pytest.mark.asyncio
async def test_intent_classifier_keyword_signals_and_site_aggregation() -> None:
    classifier = IntentClassifier()
    ecommerce_page = _page(
        "https://shop.example.com",
        "Buy Now",
        "Add to cart and checkout for fast shipping",
        meta="Shop products and pricing",
        h1s=["Shop"],
    )
    saas_page = _page(
        "https://app.example.com",
        "Platform Dashboard",
        "Start free trial and explore API integrations with pricing plans",
        meta="SaaS platform",
        h1s=["Features"],
    )
    sparse_page = _page("https://misc.example.com", "Hello", "Welcome", meta="hi")

    ecommerce_intent = await classifier.classify_page(ecommerce_page)
    saas_intent = await classifier.classify_page(saas_page)
    unknown_intent = await classifier.classify_page(sparse_page)

    assert ecommerce_intent.category == "ecommerce"
    assert ecommerce_intent.confidence > 0.4
    assert "scores" in ecommerce_intent.signals

    assert saas_intent.category == "saas"
    assert saas_intent.confidence > 0.4

    assert unknown_intent.category == "unknown"
    assert unknown_intent.confidence < 0.5

    site_intent = await classifier.classify_site(CrawlResult(pages=[ecommerce_page, ecommerce_page, saas_page]))
    assert site_intent.primary == "ecommerce"
    assert "saas" in site_intent.secondary
    assert len(site_intent.page_intents) == 3


def test_injection_generator_personalizes_by_intent() -> None:
    generator = InjectionGenerator()

    class _Intent:
        primary = "ecommerce"
        secondary = ["lead_gen"]
        page_intents = []

    embed = generator.generate("api-key-123", _Intent(), options={})
    assert 'data-archon-key="api-key-123"' in embed.script_tag
    assert embed.suggested_greeting == "How can I help you find something?"
    assert embed.suggested_mode == "growth"

    class _DocsIntent:
        primary = "docs"
        secondary: list[str] = []
        page_intents: list[Any] = []

    docs_embed = generator.generate("k2", _DocsIntent(), options={})
    assert docs_embed.suggested_mode == "debate"
    snippet = generator.generate_full_snippet(docs_embed)
    assert "<!-- ARCHON Embed: start -->" in snippet
    assert docs_embed.script_tag in snippet


def _base_embed_config() -> Any:
    class _Intent:
        primary = "blog"
        secondary: list[str] = []
        page_intents: list[Any] = []

    return InjectionGenerator().generate("test-key", _Intent(), options={})


def test_optimizer_agent_experiment_lifecycle_and_clear_winner() -> None:
    optimizer = OptimizerAgent()
    experiment = optimizer.create_experiment(_base_embed_config())
    assert experiment.control_variant_id in experiment.variants
    assert experiment.challenger_variant_id in experiment.variants

    optimizer.record_event(experiment.experiment_id, experiment.control_variant_id, "impression")
    optimizer.record_event(experiment.experiment_id, experiment.control_variant_id, "engagement")
    optimizer.record_event(experiment.experiment_id, experiment.control_variant_id, "conversion")
    control = experiment.variants[experiment.control_variant_id]
    assert control.impressions == 1
    assert control.engagements == 1
    assert control.conversions == 1

    for _ in range(200):
        optimizer.record_event(experiment.experiment_id, experiment.control_variant_id, "impression")
        optimizer.record_event(experiment.experiment_id, experiment.challenger_variant_id, "impression")
    for _ in range(10):
        optimizer.record_event(experiment.experiment_id, experiment.control_variant_id, "conversion")
    for _ in range(50):
        optimizer.record_event(experiment.experiment_id, experiment.challenger_variant_id, "conversion")

    result = optimizer.evaluate_experiment(experiment.experiment_id)
    assert result.winner == experiment.challenger_variant_id
    assert result.confidence > 0.95
    assert result.lift_pct > 0

    improved = optimizer.suggest_improvement(experiment.experiment_id)
    assert improved.config_json.get("optimizer", {}).get("winner") == experiment.challenger_variant_id


def test_optimizer_agent_insufficient_data_has_no_winner() -> None:
    optimizer = OptimizerAgent()
    experiment = optimizer.create_experiment(_base_embed_config())
    for _ in range(5):
        optimizer.record_event(experiment.experiment_id, experiment.control_variant_id, "impression")
        optimizer.record_event(experiment.experiment_id, experiment.challenger_variant_id, "impression")
    result = optimizer.evaluate_experiment(experiment.experiment_id)
    assert result.winner is None
    assert result.confidence == 0.0

