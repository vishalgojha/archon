from __future__ import annotations

import json
from typing import Any

import click

from archon.cli import renderer
from archon.cli.base_command import ArchonCommand
from archon.cli.copy import DRAWER_COPY
from archon.providers import ProviderRouter
from archon.web.injection_generator import InjectionGenerator
from archon.web.intent_classifier import IntentClassifier
from archon.web.optimizer_agent import OptimizerAgent
from archon.web.site_crawler import CrawlResult, PageData, SiteCrawler

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


def _page_prompt_payload(pages: list[PageData], *, max_chars: int = 1200) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for page in pages:
        excerpt = page.text_content.strip()
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars].rstrip() + "..."
        payload.append(
            {
                "url": page.url,
                "title": page.title,
                "meta": page.meta_description,
                "h1s": list(page.h1s),
                "text_excerpt": excerpt,
                "load_ms": page.load_ms,
            }
        )
    return payload


def _build_optimize_prompt(
    *,
    url: str,
    pages: list[PageData],
    site_intent,  # type: ignore[no-untyped-def]
) -> str:
    page_payload = _page_prompt_payload(pages)
    intent_payload = {
        "primary": getattr(site_intent, "primary", "unknown"),
        "secondary": list(getattr(site_intent, "secondary", [])),
    }
    lines = [
        "Optimize this page for conversion.",
        "Provide concise, prioritized recommendations",
        "with quick wins and copy tweaks.",
        "Return plain text bullets.",
        f"Target URL: {url}",
        f"Site intent: {json.dumps(intent_payload)}",
        f"Page summaries: {json.dumps(page_payload)}",
    ]
    return "\n".join(lines)


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
        generator = (
            InjectionGenerator(script_src=script_src) if script_src else InjectionGenerator()
        )
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


class _Optimize(ArchonCommand):
    command_id = COMMAND_IDS[1]

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
        live_providers: bool,
        config_path: str,
        llm: bool,
    ):
        config, normalized_url = session.run_step(
            0, _load_config_and_url, self.bindings, config_path, url
        )
        crawl_result = await session.run_step_async(
            1, _crawl_site, normalized_url, max_pages, max_depth
        )
        router = ProviderRouter(config=config, live_mode=llm) if llm else None
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
        generator = (
            InjectionGenerator(script_src=script_src) if script_src else InjectionGenerator()
        )
        embed = session.run_step(3, generator.generate, embed_key, site_intent, options)
        optimizer = OptimizerAgent()
        experiment = session.run_step(4, optimizer.create_experiment, embed)
        improved = session.run_step(5, optimizer.suggest_improvement, experiment.experiment_id)

        orchestrator = session.run_step(
            6,
            self.bindings.Orchestrator,
            config=config,
            live_provider_calls=live_providers,
        )
        session.update_step(7, "running")
        try:
            result = await orchestrator.execute(
                goal=_build_optimize_prompt(
                    url=normalized_url,
                    pages=crawl_result.pages,
                    site_intent=site_intent,
                ),
                mode="debate",
            )
        finally:
            await orchestrator.aclose()
        session.update_step(7, "success")

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
            "experiment": {
                "experiment_id": experiment.experiment_id,
                "control_variant_id": experiment.control_variant_id,
                "challenger_variant_id": experiment.challenger_variant_id,
                "recommended_config": improved.config_json,
            },
            "recommendations": result.final_answer,
        }
        session.print(renderer.detail_panel(self.command_id, [json.dumps(payload, indent=2)]))
        return {
            "page_count": len(crawl_result.pages),
            "primary_intent": site_intent.primary,
            "experiment_id": experiment.experiment_id,
            "confidence": result.confidence,
        }


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
    @click.argument("url")
    @click.option("--max-pages", default=6, type=int)
    @click.option("--max-depth", default=1, type=int)
    @click.option("--api-key", default=None)
    @click.option("--mode", default=None)
    @click.option("--greeting", default=None)
    @click.option("--script-src", default=None)
    @click.option("--live-providers", is_flag=True, default=False)
    @click.option("--config", "config_path", default="config.archon.yaml")
    @click.option("--llm/--no-llm", default=False)
    def optimize_command(
        url: str,
        max_pages: int,
        max_depth: int,
        api_key: str | None,
        mode: str | None,
        greeting: str | None,
        script_src: str | None,
        live_providers: bool,
        config_path: str,
        llm: bool,
    ) -> None:
        _Optimize(bindings).invoke(
            url=url,
            max_pages=max_pages,
            max_depth=max_depth,
            api_key=api_key,
            mode=mode,
            greeting=greeting,
            script_src=script_src,
            live_providers=live_providers,
            config_path=config_path,
            llm=llm,
        )

    return group
