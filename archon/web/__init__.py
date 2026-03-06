"""Web analysis, injection, and optimization tooling."""

from archon.web.injection_generator import EmbedConfig, InjectionGenerator
from archon.web.intent_classifier import IntentClassifier, PageIntent, SiteIntent
from archon.web.optimizer_agent import ABVariant, Experiment, ExperimentResult, OptimizerAgent
from archon.web.site_crawler import CrawlResult, PageData, SiteCrawler

__all__ = [
    "ABVariant",
    "CrawlResult",
    "EmbedConfig",
    "Experiment",
    "ExperimentResult",
    "InjectionGenerator",
    "IntentClassifier",
    "OptimizerAgent",
    "PageData",
    "PageIntent",
    "SiteCrawler",
    "SiteIntent",
]
