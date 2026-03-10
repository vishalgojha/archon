from __future__ import annotations

from types import SimpleNamespace

from archon.cli.drawers.web import _build_optimize_prompt, _page_prompt_payload
from archon.web.site_crawler import PageData


def _sample_page(text: str) -> PageData:
    return PageData(
        url="https://example.com",
        title="Example",
        text_content=text,
        meta_description="Meta",
        h1s=["Headline"],
        links=["https://example.com/about"],
        load_ms=12.5,
    )


def test_page_prompt_payload_truncates_excerpt() -> None:
    long_text = "a" * 1300
    payload = _page_prompt_payload([_sample_page(long_text)], max_chars=1200)

    assert payload
    excerpt = payload[0]["text_excerpt"]
    assert excerpt.endswith("...")
    assert len(excerpt) <= 1203


def test_build_optimize_prompt_includes_url_and_intent() -> None:
    intent = SimpleNamespace(primary="saas", secondary=["docs"])
    page = _sample_page("short text")

    prompt = _build_optimize_prompt(url=page.url, pages=[page], site_intent=intent)

    assert "Optimize this page for conversion." in prompt
    assert page.url in prompt
    assert '"primary": "saas"' in prompt
