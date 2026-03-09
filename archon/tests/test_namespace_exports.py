"""Import-contract tests for package-level namespace exports."""

from __future__ import annotations

import archon.agents.domain as domain
import archon.evolution as evolution
import archon.federation as federation
import archon.interfaces.embed as embed
import archon.vision as vision
import archon.web_transform as web_transform
from archon.agents.community.community_agent import CommunityAgent, SignalDetector
from archon.agents.content.content_agent import ContentAgent, SEOOptimizer
from archon.evolution.ab_tester import ABTester
from archon.evolution.engine import SelfEvolutionEngine, WorkflowDefinition
from archon.federation.collab import CollabOrchestrator, TaskBroker
from archon.federation.peer_discovery import PeerRegistry
from archon.vision.action_agent import ActionAgent
from archon.vision.ui_parser import UIParser
from archon.web.injection_generator import EmbedConfig, InjectionGenerator
from archon.web.intent_classifier import IntentClassifier, SiteIntent
from archon.web.optimizer_agent import OptimizerAgent
from archon.web.site_crawler import PageData, SiteCrawler


def test_domain_namespace_re_exports_domain_agents() -> None:
    assert domain.CommunityAgent is CommunityAgent
    assert domain.SignalDetector is SignalDetector
    assert domain.ContentAgent is ContentAgent
    assert domain.SEOOptimizer is SEOOptimizer
    assert {"CommunityAgent", "ContentAgent", "SEOOptimizer"}.issubset(domain.__all__)


def test_embed_namespace_re_exports_web_embed_pipeline() -> None:
    assert embed.EmbedConfig is EmbedConfig
    assert embed.InjectionGenerator is InjectionGenerator
    assert embed.IntentClassifier is IntentClassifier
    assert embed.SiteCrawler is SiteCrawler
    assert embed.OptimizerAgent is OptimizerAgent
    assert {"EmbedConfig", "InjectionGenerator", "OptimizerAgent"}.issubset(embed.__all__)


def test_web_transform_namespace_re_exports_crawl_and_intent_types() -> None:
    assert web_transform.SiteCrawler is SiteCrawler
    assert web_transform.IntentClassifier is IntentClassifier
    assert web_transform.PageData is PageData
    assert web_transform.SiteIntent is SiteIntent
    assert "ARCHON_CRAWLER_USER_AGENT" in web_transform.__all__


def test_vision_namespace_re_exports_public_surface() -> None:
    assert vision.ActionAgent is ActionAgent
    assert vision.UIParser is UIParser
    assert {"ActionAgent", "ScreenCapture", "UIParser"}.issubset(vision.__all__)


def test_evolution_namespace_re_exports_public_surface() -> None:
    assert evolution.ABTester is ABTester
    assert evolution.SelfEvolutionEngine is SelfEvolutionEngine
    assert evolution.WorkflowDefinition is WorkflowDefinition
    assert {"ABTester", "SelfEvolutionEngine", "WorkflowDefinition"}.issubset(evolution.__all__)


def test_federation_namespace_re_exports_public_surface() -> None:
    assert federation.TaskBroker is TaskBroker
    assert federation.CollabOrchestrator is CollabOrchestrator
    assert federation.PeerRegistry is PeerRegistry
    assert {"TaskBroker", "CollabOrchestrator", "PeerRegistry"}.issubset(federation.__all__)
