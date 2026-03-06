"""Tests for multilingual SEO content generation and publishing workflows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from archon.agents.content.content_agent import (
    ContentAgent,
    ContentBrief,
    ContentPiece,
    ContentScheduler,
    PublishingQueue,
    PublishTarget,
    SEOOptimizer,
)


def _tmp_file(prefix: str) -> Path:
    base = Path("archon/tests/_tmp_content")
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{prefix}-{uuid.uuid4().hex[:8]}.md"


@dataclass(slots=True)
class _FakePipelineResult:
    detected_language: str
    response_language: str
    response_content: str
    method: str
    confidence: float


class _FakePipeline:
    def __init__(self, response_content: str) -> None:
        self.response_content = response_content
        self.calls: list[tuple[str, str | None]] = []

    def process(self, user_input: str, force_language: str | None = None) -> _FakePipelineResult:
        self.calls.append((user_input, force_language))
        return _FakePipelineResult(
            detected_language=force_language or "en",
            response_language=force_language or "en",
            response_content=self.response_content,
            method="native_reasoning",
            confidence=0.9,
        )


class _RecordingGate:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def check(self, action: str, context: dict, action_id: str) -> str:  # type: ignore[override]
        self.calls.append({"action": action, "context": context, "action_id": action_id})
        return action_id


def test_brief_from_icp_generates_language_and_keywords() -> None:
    pipeline = _FakePipeline(
        '{"target_audience":"Revenue teams","keywords":["sales automation","pipeline visibility"],'
        '"tone":"practical","word_count_target":1100}'
    )
    agent = ContentAgent(
        icp_agent=object(),
        vernacular_pipeline=pipeline,
        approval_gate=None,
        publish_targets=[PublishTarget(target_id="stdout", type="stdout", config={})],
    )

    brief = agent.brief_from_icp(
        icp={"target_audience": "B2B SaaS", "pain_points": ["manual follow-up", "low conversion"]},
        language_code="es",
        topic="How to improve outbound conversion",
    )

    assert brief.target_language == "es"
    assert brief.keywords
    assert brief.word_count_target >= 600


def test_content_piece_generate_mocked_llm_returns_piece_with_slug() -> None:
    article = (
        "# Revenue Pipeline Playbook\n"
        "Intro paragraph for the article.\n\n"
        "## Section One\nDetails one.\n\n"
        "## Section Two\nDetails two.\n\n"
        "## Section Three\nDetails three.\n\n"
        "## Conclusion\nFinal thought.\n\n"
        "## CTA\nUse ARCHON to automate your pipeline."
    )
    pipeline = _FakePipeline(article)
    brief = ContentBrief(
        brief_id="brief-1",
        topic="Pipeline automation",
        target_language="en",
        target_audience="Revenue leaders",
        keywords=["pipeline automation", "sales workflow"],
        tone="expert",
        word_count_target=1200,
    )

    piece = ContentPiece.generate(brief, pipeline=pipeline)

    assert piece.title
    assert piece.body
    assert piece.slug
    assert piece.language_code == "en"


def test_seo_optimizer_density_meta_readability_and_links() -> None:
    optimizer = SEOOptimizer()
    brief = ContentBrief(
        brief_id="brief-2",
        topic="SEO automation",
        target_language="en",
        target_audience="Marketing teams",
        keywords=["alpha"],
        tone="practical",
        word_count_target=900,
    )
    piece = ContentPiece(
        piece_id="piece-2",
        brief=brief,
        title="Alpha Strategy",
        body=(
            "alpha beta alpha gamma alpha. "
            "This is a very long body intended to exercise metadata truncation and readability scoring. "
            "ARCHON helps teams automate content and workflow planning across regions."
        ),
        meta_description="",
        slug="en-alpha-strategy",
        language_code="en",
        word_count=0,
    )

    density = optimizer.keyword_density("alpha beta alpha gamma alpha", "alpha")
    assert round(density, 2) == 60.00

    meta = optimizer.generate_meta(piece)
    assert len(meta) <= 155

    readability = optimizer.readability_score(piece.body)
    assert 0.0 <= readability <= 1.0

    linked = optimizer.add_internal_links(piece, {"ARCHON": "/product/archon"})
    assert "[ARCHON](/product/archon)" in linked.body


def test_publishing_queue_queue_publish_gate_file_and_mark_published() -> None:
    brief = ContentBrief(
        brief_id="brief-3",
        topic="Automation",
        target_language="en",
        target_audience="Operators",
        keywords=["automation"],
        tone="neutral",
        word_count_target=800,
    )
    piece = ContentPiece(
        piece_id="piece-3",
        brief=brief,
        title="Automation Guide",
        body="## Intro\nBody\n\n## CTA\nUse ARCHON capability.",
        meta_description="desc",
        slug="en-automation-guide",
        language_code="en",
        word_count=10,
    )

    gate = _RecordingGate()
    file_path = _tmp_file("publish")
    calls: list[dict] = []

    queue = PublishingQueue(
        targets=[
            PublishTarget(
                target_id="webhook-1",
                type="webhook",
                config={
                    "url": "https://example.invalid/webhook",
                    "sender": lambda payload: calls.append(payload),
                },
            ),
            PublishTarget(target_id="file-1", type="file", config={"path": str(file_path)}),
        ],
        approval_gate=gate,
    )

    queue.queue(piece)
    assert len(queue.get_queue()) == 1

    first = queue.publish_next()
    assert first is not None
    assert first.target_id == "webhook-1"
    assert gate.calls and gate.calls[0]["action"] == "external_api_call"

    second = queue.publish_next()
    assert second is not None
    assert second.target_id == "file-1"
    assert file_path.exists()

    queue.mark_published(piece.piece_id, "webhook-1")
    queue.mark_published(piece.piece_id, "file-1")
    assert queue.get_queue() == []


def test_content_scheduler_schedule_and_next_run_future() -> None:
    def _builder(icp: dict, language_code: str, topic: str) -> ContentBrief:
        return ContentBrief(
            brief_id=f"brief-{language_code}",
            topic=topic,
            target_language=language_code,
            target_audience=str(icp.get("audience", "users")),
            keywords=["keyword"],
            tone="neutral",
            word_count_target=1000,
        )

    scheduler = ContentScheduler(_builder)
    briefs = scheduler.schedule(
        topic="International SEO",
        languages=["en", "fr", "de"],
        icp={"audience": "growth teams"},
        cadence_days=7,
    )

    assert len(briefs) == 3
    assert {brief.target_language for brief in briefs} == {"en", "fr", "de"}

    schedule_id = scheduler.schedule_ids()[0]
    next_run = scheduler.next_run(schedule_id)
    assert next_run > datetime.now(timezone.utc)


def test_content_agent_run_scheduled_generates_and_queues_due_pieces() -> None:
    article = (
        "# Multilingual Growth\n"
        "Intro text\n\n"
        "## Section A\nA\n\n"
        "## Section B\nB\n\n"
        "## Section C\nC\n\n"
        "## Conclusion\nDone\n\n"
        "## CTA\nUse ARCHON for multilingual execution"
    )
    pipeline = _FakePipeline(article)
    agent = ContentAgent(
        icp_agent=object(),
        vernacular_pipeline=pipeline,
        approval_gate=None,
        publish_targets=[PublishTarget(target_id="stdout", type="stdout", config={})],
    )

    agent.schedule(
        topic="Global content strategy",
        languages=["en", "es"],
        icp={"target_audience": "marketers", "pain_points": ["translation delays"]},
        cadence_days=7,
    )

    schedule_id = agent.scheduler.schedule_ids()[0]
    # Force due run by moving next_run into the past.
    agent.scheduler._schedules[schedule_id].next_run_at = datetime.now(timezone.utc) - timedelta(
        minutes=1
    )

    pieces = agent.run_scheduled()

    assert len(pieces) == 2
    assert len(agent.queue.get_queue()) == 2
