"""Domain-specific agent surfaces."""

from archon.agents.community.community_agent import (
    ActionResult,
    CommunityAgent,
    CommunityPost,
    DetectionResult,
    DraftResponse,
    HNCollector,
    RSSCollector,
    RedditCollector,
    ResponseComposer,
    SignalDetector,
)
from archon.agents.content.content_agent import (
    ContentAgent,
    ContentBrief,
    ContentPiece,
    ContentScheduler,
    OptimizedPiece,
    PublishingQueue,
    PublishResult,
    PublishTarget,
    SEOOptimizer,
)

__all__ = [
    "ActionResult",
    "CommunityAgent",
    "CommunityPost",
    "ContentAgent",
    "ContentBrief",
    "ContentPiece",
    "ContentScheduler",
    "DetectionResult",
    "DraftResponse",
    "HNCollector",
    "OptimizedPiece",
    "PublishingQueue",
    "PublishResult",
    "PublishTarget",
    "RSSCollector",
    "RedditCollector",
    "ResponseComposer",
    "SEOOptimizer",
    "SignalDetector",
]
