from __future__ import annotations

import json
from typing import Any

import click

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand, PlaceholderCommand
from archon.cli.copy import DRAWER_COPY
from archon.providers import ProviderRouter
from archon.web.injection_generator import InjectionGenerator
from archon.web.intent_classifier import IntentClassifier
from archon.web.site_crawler import CrawlResult, SiteCrawler

DRAWER_ID = "web"
COMMAND_IDS = ("web.crawl", "web.optimize")
DRAWER_META = DRAWER_COPY[DRAWER_ID]
COMMAND_HELP = DRAWER_META["commands"]


def _validate_url(url: str) -> str:
    cleaned = str(url or "").strip()
    if not cleaned:
        raise click.ClickException("URL is required.")
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise click.ClickException("URL must start with http:// or https://")
    return cleaned


def _load_config_and_url(bindings: Any, config_path: str, url: str):  # type: ignore[no-untyped-def]
    config = bindings._load_config(config_path)
    return config, _validate_url(url)


async def _crawl_site(url: str, max_pages: int, max_depth: int) -> CrawlResult:
    crawler = SiteCrawler(max_concurrent=3, delay_between_requests_ms=0)
    try:
        result = await crawler.crawl(url, max_pages=max_pages, max_depth=max_depth)
    finally:
        await crawler.aclose()
    if not result.pages:
        raise click.ClickException("No crawlable pages found.")
    return result


def _intent_payload(site_intent):  # type: ignore[no-untyped-def]
    return {
        "primary": site_intent.primary,
        "secondary": list(site_intent.secondary),
        "page_intents": [
            {"category": intent.category, "confidence": intent.confidence}
            for intent in site_intent.page_intents
        ],
    }


def _page_payload(result: CrawlResult) -> list[dict[str, Any]]:
    return [
        {
            "url": page.url,
            "title": page.title,
            "meta": page.meta_description,
            "h1s": list(page.h1s),
        }
        for page in result.pages
    ]


class _Crawl(ArchonCommand):
    command_id = COMMAND_IDS[0]

    async def run(  # type: ignore[no-untyped-def,override]
        self,
        session,
        *,
        url: str,
        max_pages: int,
        max_depth: int,
        api_key: str | None,
        mode: str | None,
        greeting: str | None,
        script_src: str | None,
        config_path: str,
        llm: bool,
    ):
        config, normalized_url = session.run_step(
            0, _load_config_and_url, self.bindings, config_path, url
        )
        crawl_result = await session.run_step_async(
            1, _crawl_site, normalized_url, max_pages, max_depth
        )
        router = ProviderRouter(config=config, live_mode=True) if llm else None
        classifier = IntentClassifier(router=router)
        try:
            site_intent = await session.run_step_async(2, classifier.classify_site, crawl_result)
        finally:
            if router is not None:
                await router.aclose()
        options: dict[str, Any] = {}
        if mode:
            options["mode"] = mode
        if greeting:
            options["greeting"] = greeting
        embed_key = str(api_key or "archon-demo-key")
        generator = InjectionGenerator(script_src=script_src) if script_src else InjectionGenerator()
        embed = session.run_step(3, generator.generate, embed_key, site_intent, options)
        payload = {
            "url": normalized_url,
            "pages": _page_payload(crawl_result),
            "site_intent": _intent_payload(site_intent),
            "embed": {
                "script_tag": embed.script_tag,
                "snippet": generator.generate_full_snippet(embed),
                "suggested_mode": embed.suggested_mode,
                "suggested_greeting": embed.suggested_greeting,
            },
        }
        session.print(renderer.detail_panel(self.command_id, [json.dumps(payload, indent=2)]))
        return {
            "page_count": len(crawl_result.pages),
            "primary_intent": site_intent.primary,
            "suggested_mode": embed.suggested_mode,
        }


class _Optimize(PlaceholderCommand):
    command_id = COMMAND_IDS[1]


def build_group(bindings):
    @click.group(
        name=DRAWER_ID,
        invoke_without_command=True,
        help=str(DRAWER_META["tagline"]),
    )
    @click.pass_context
    def group(ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            renderer.emit(renderer.drawer_panel(DRAWER_ID))

    @group.command("crawl", help=str(COMMAND_HELP[COMMAND_IDS[0]]))
    @click.argument("url")
    @click.option("--max-pages", default=6, type=int)
    @click.option("--max-depth", default=1, type=int)
    @click.option("--api-key", default=None)
    @click.option("--mode", default=None)
    @click.option("--greeting", default=None)
    @click.option("--script-src", default=None)
    @click.option("--config", "config_path", default="config.archon.yaml")
    @click.option("--llm/--no-llm", default=False)
    def crawl_command(
        url: str,
        max_pages: int,
        max_depth: int,
        api_key: str | None,
        mode: str | None,
        greeting: str | None,
        script_src: str | None,
        config_path: str,
        llm: bool,
    ) -> None:
        _Crawl(bindings).invoke(
            url=url,
            max_pages=max_pages,
            max_depth=max_depth,
            api_key=api_key,
            mode=mode,
            greeting=greeting,
            script_src=script_src,
            config_path=config_path,
            llm=llm,
        )

    @group.command("optimize", help=str(COMMAND_HELP[COMMAND_IDS[1]]))
    def optimize_command() -> None:
        _Optimize(bindings).invoke()

    return group
