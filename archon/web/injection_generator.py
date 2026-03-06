"""Embed snippet generation for ARCHON web integrations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from archon.web.intent_classifier import SiteIntent


@dataclass(slots=True, frozen=True)
class EmbedConfig:
    """Generated embed settings and script content."""

    script_tag: str
    config_json: dict[str, Any]
    suggested_greeting: str
    suggested_mode: str


class InjectionGenerator:
    """Builds personalized ARCHON embed tags and snippets."""

    def __init__(self, *, script_src: str = "https://cdn.archon.ai/embed.js") -> None:
        self.script_src = script_src

    def generate(
        self,
        api_key: str,
        site_intent: SiteIntent,
        options: dict[str, Any] | None = None,
    ) -> EmbedConfig:
        """Generate an embed config from API key + detected site intent."""

        options = dict(options or {})
        intent = site_intent.primary
        mode = options.get("mode") or _suggest_mode(intent)
        greeting = options.get("greeting") or _suggest_greeting(intent)

        config: dict[str, Any] = {
            "apiKey": api_key,
            "mode": mode,
            "greeting": greeting,
            "intent": intent,
            "secondaryIntents": site_intent.secondary,
            "options": {k: v for k, v in options.items() if k not in {"mode", "greeting"}},
        }
        script_tag = (
            f'<script src="{self.script_src}" data-archon-key="{api_key}" '
            f'data-archon-mode="{mode}"></script>'
        )
        return EmbedConfig(
            script_tag=script_tag,
            config_json=config,
            suggested_greeting=greeting,
            suggested_mode=mode,
        )

    def generate_full_snippet(self, embed_config: EmbedConfig) -> str:
        """Generate full copy-paste snippet with setup instructions."""

        config_json = json.dumps(embed_config.config_json, indent=2)
        return (
            "<!-- ARCHON Embed: start -->\n"
            "<!-- 1) Paste script tag before </body> -->\n"
            f"{embed_config.script_tag}\n"
            "<!-- 2) Optional config bootstrap -->\n"
            "<script>\n"
            "window.ARCHON_CONFIG = "
            f"{config_json};\n"
            "</script>\n"
            "<!-- ARCHON Embed: end -->"
        )


def _suggest_mode(intent: str) -> str:
    if intent in {"ecommerce", "lead_gen"}:
        return "growth"
    if intent == "docs":
        return "debate"
    if intent == "blog":
        return "auto"
    return "auto"


def _suggest_greeting(intent: str) -> str:
    if intent == "ecommerce":
        return "How can I help you find something?"
    if intent == "lead_gen":
        return "Want help picking the right solution for your needs?"
    if intent == "docs":
        return "Need help finding the right documentation quickly?"
    if intent == "saas":
        return "Want a quick walkthrough of our platform features?"
    if intent == "blog":
        return "Looking for a specific article or topic?"
    if intent == "news":
        return "Want a quick summary of the latest updates?"
    if intent == "portfolio":
        return "Want to explore selected projects by category?"
    return "How can I help today?"
