"""Multilingual SEO content generation and publishing workflow."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from archon.agents.growth.icp import ICPAgent
from archon.core.approval_gate import ApprovalGate
from archon.vernacular.detector import SUPPORTED_LANGUAGES
from archon.vernacular.pipeline import VernacularPipeline


def _now() -> float:
    return time.time()


def _brief_id() -> str:
    return f"brief-{uuid.uuid4().hex[:12]}"


def _piece_id() -> str:
    return f"piece-{uuid.uuid4().hex[:12]}"


def _schedule_id() -> str:
    return f"schedule-{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class ContentBrief:
    brief_id: str
    topic: str
    target_language: str
    target_audience: str
    keywords: list[str]
    tone: str
    word_count_target: int


@dataclass(slots=True)
class ContentPiece:
    piece_id: str
    brief: ContentBrief
    title: str
    body: str
    meta_description: str
    slug: str
    language_code: str
    word_count: int
    created_at: float = field(default_factory=_now)

    @classmethod
    def generate(
        cls,
        brief: ContentBrief,
        *,
        pipeline: VernacularPipeline,
        topic_context: dict[str, Any] | None = None,
    ) -> "ContentPiece":
        prompt = _article_prompt(brief, topic_context=topic_context or {})
        result = pipeline.process(prompt, force_language=brief.target_language)

        title, raw_body = _split_title_and_body(result.response_content, brief.topic)
        body = _enforce_article_structure(raw_body, brief=brief)
        slug = _slugify(title, brief.target_language)
        meta = _meta_from_body(title=title, body=body)
        word_count = _word_count(body)

        return cls(
            piece_id=_piece_id(),
            brief=brief,
            title=title,
            body=body,
            meta_description=meta,
            slug=slug,
            language_code=brief.target_language,
            word_count=word_count,
            created_at=_now(),
        )


@dataclass(slots=True)
class OptimizedPiece:
    piece: ContentPiece
    keyword_density: dict[str, float]
    readability: float


class SEOOptimizer:
    """Pure-python SEO polishing helpers."""

    def optimize(self, piece: ContentPiece, keywords: list[str]) -> OptimizedPiece:
        densities = {keyword: self.keyword_density(piece.body, keyword) for keyword in keywords}
        readability = self.readability_score(piece.body)
        refreshed_meta = self.generate_meta(piece)
        refined_piece = replace(piece, meta_description=refreshed_meta)
        return OptimizedPiece(
            piece=refined_piece, keyword_density=densities, readability=readability
        )

    def keyword_density(self, text: str, keyword: str) -> float:
        words = _tokenize(text)
        if not words:
            return 0.0
        keyword_tokens = _tokenize(keyword)
        if not keyword_tokens:
            return 0.0

        matches = 0
        window = len(keyword_tokens)
        for index in range(len(words) - window + 1):
            if words[index : index + window] == keyword_tokens:
                matches += 1

        density = (matches * window / len(words)) * 100.0
        return round(density, 4)

    def add_internal_links(self, piece: ContentPiece, site_map: dict[str, str]) -> ContentPiece:
        updated_body = piece.body
        for anchor, url in site_map.items():
            clean_anchor = str(anchor or "").strip()
            clean_url = str(url or "").strip()
            if not clean_anchor or not clean_url:
                continue
            pattern = re.compile(rf"\b({re.escape(clean_anchor)})\b", re.IGNORECASE)
            if "[" in updated_body and f"]({clean_url})" in updated_body:
                continue
            updated_body, count = pattern.subn(rf"[\1]({clean_url})", updated_body, count=1)
            if count == 0:
                continue
        return replace(piece, body=updated_body)

    def generate_meta(self, piece: ContentPiece) -> str:
        return _meta_from_body(title=piece.title, body=piece.body)

    def readability_score(self, text: str) -> float:
        words = _tokenize(text)
        if not words:
            return 0.0

        sentence_count = max(1, len(re.findall(r"[.!?]+", text)))
        syllables = sum(_count_syllables(word) for word in words)
        words_per_sentence = len(words) / sentence_count
        syllables_per_word = syllables / len(words)

        flesch = 206.835 - (1.015 * words_per_sentence) - (84.6 * syllables_per_word)
        normalized = max(0.0, min(1.0, flesch / 100.0))
        return round(normalized, 4)


@dataclass(slots=True)
class PublishTarget:
    target_id: str
    type: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PublishResult:
    piece_id: str
    target_id: str
    status: str
    detail: str
    published_at: float


@dataclass(slots=True)
class _QueueEntry:
    piece: ContentPiece
    published_targets: set[str] = field(default_factory=set)


class PublishingQueue:
    """In-memory publish queue with approval-gated webhook support."""

    def __init__(
        self,
        targets: list[PublishTarget],
        *,
        approval_gate: ApprovalGate | None = None,
        event_sink=None,
    ) -> None:
        self.targets = list(targets)
        self.approval_gate = approval_gate
        self.event_sink = event_sink
        self._queue: list[_QueueEntry] = []

    def queue(self, piece: ContentPiece) -> None:
        self._queue.append(_QueueEntry(piece=piece))

    def get_queue(self) -> list[ContentPiece]:
        return [entry.piece for entry in self._queue]

    def publish_next(self) -> PublishResult | None:
        if not self._queue:
            return None

        entry = self._queue[0]
        next_target = next(
            (target for target in self.targets if target.target_id not in entry.published_targets),
            None,
        )
        if next_target is None:
            self._queue.pop(0)
            return None

        if next_target.type == "webhook":
            self._approve_webhook(entry.piece, next_target)
            detail = self._publish_webhook(entry.piece, next_target)
        elif next_target.type == "file":
            detail = self._publish_file(entry.piece, next_target)
        elif next_target.type == "stdout":
            detail = self._publish_stdout(entry.piece, next_target)
        else:
            raise ValueError(f"Unsupported publish target type '{next_target.type}'.")

        result = PublishResult(
            piece_id=entry.piece.piece_id,
            target_id=next_target.target_id,
            status="published",
            detail=detail,
            published_at=_now(),
        )
        self.mark_published(entry.piece.piece_id, next_target.target_id)
        return result

    def mark_published(self, piece_id: str, target_id: str) -> None:
        clean_piece = str(piece_id or "").strip()
        clean_target = str(target_id or "").strip()
        for index, entry in enumerate(self._queue):
            if entry.piece.piece_id != clean_piece:
                continue
            entry.published_targets.add(clean_target)
            all_targets = {target.target_id for target in self.targets}
            if all_targets.issubset(entry.published_targets):
                self._queue.pop(index)
            return

    def _approve_webhook(self, piece: ContentPiece, target: PublishTarget) -> None:
        if self.approval_gate is None:
            return
        action_id = f"content-publish-{piece.piece_id}-{target.target_id}"
        context = {
            "piece_id": piece.piece_id,
            "target_id": target.target_id,
            "target_url": str(target.config.get("url", "")),
            "topic": piece.brief.topic,
            "event_sink": self.event_sink,
            "timeout_seconds": float(target.config.get("approval_timeout_seconds", 5.0)),
        }

        maybe_awaitable = self.approval_gate.check(
            action="external_api_call",
            context=context,
            action_id=action_id,
        )
        _run_maybe_awaitable(maybe_awaitable)

    def _publish_webhook(self, piece: ContentPiece, target: PublishTarget) -> str:
        sender = target.config.get("sender")
        payload = {
            "piece_id": piece.piece_id,
            "title": piece.title,
            "body": piece.body,
            "meta_description": piece.meta_description,
            "language_code": piece.language_code,
            "slug": piece.slug,
        }
        if callable(sender):
            sender(payload)
            return "Webhook sender callback invoked."
        return f"Webhook payload prepared for {target.config.get('url', 'unknown')}"

    def _publish_file(self, piece: ContentPiece, target: PublishTarget) -> str:
        raw_path = str(target.config.get("path") or "").strip()
        if not raw_path:
            raise ValueError("File target requires config.path")
        path = Path(raw_path)
        if path.suffix:
            destination = path
        else:
            destination = path / f"{piece.slug}.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(_as_markdown(piece), encoding="utf-8")
        return f"Wrote markdown file to {destination}"

    def _publish_stdout(self, piece: ContentPiece, target: PublishTarget) -> str:
        del target
        print(_as_markdown(piece))
        return "Printed markdown to stdout"


@dataclass(slots=True)
class _ScheduleEntry:
    schedule_id: str
    topic: str
    languages: list[str]
    icp: dict[str, Any]
    cadence_days: int
    next_run_at: datetime


class ContentScheduler:
    """Schedules multilingual brief cycles."""

    def __init__(
        self,
        brief_builder: Callable[[dict[str, Any], str, str], ContentBrief],
    ) -> None:
        self.brief_builder = brief_builder
        self._schedules: dict[str, _ScheduleEntry] = {}

    def schedule(
        self,
        topic: str,
        languages: list[str],
        icp: dict[str, Any],
        cadence_days: int = 7,
    ) -> list[ContentBrief]:
        clean_topic = str(topic or "").strip()
        normalized_languages = [
            _normalize_language_code(language)
            for language in languages
            if _normalize_language_code(language)
        ]
        if not clean_topic:
            raise ValueError("topic is required")
        if not normalized_languages:
            raise ValueError("At least one language is required")

        now = datetime.now(timezone.utc)
        schedule_id = _schedule_id()
        self._schedules[schedule_id] = _ScheduleEntry(
            schedule_id=schedule_id,
            topic=clean_topic,
            languages=normalized_languages,
            icp=dict(icp),
            cadence_days=max(1, int(cadence_days)),
            next_run_at=now + timedelta(days=max(1, int(cadence_days))),
        )

        return [self.brief_builder(icp, language, clean_topic) for language in normalized_languages]

    def next_run(self, schedule_id: str) -> datetime:
        key = str(schedule_id or "").strip()
        if key not in self._schedules:
            raise KeyError(f"Unknown schedule_id '{key}'.")
        return self._schedules[key].next_run_at

    def due_entries(self, now: datetime | None = None) -> list[_ScheduleEntry]:
        current = now or datetime.now(timezone.utc)
        return [entry for entry in self._schedules.values() if entry.next_run_at <= current]

    def advance(self, schedule_id: str) -> None:
        entry = self._schedules.get(schedule_id)
        if entry is None:
            raise KeyError(f"Unknown schedule_id '{schedule_id}'.")
        entry.next_run_at = entry.next_run_at + timedelta(days=entry.cadence_days)

    def schedule_ids(self) -> list[str]:
        return sorted(self._schedules)


class ContentAgent:
    """Generates multilingual SEO content and queues publish outputs."""

    def __init__(
        self,
        icp_agent: ICPAgent | Any,
        vernacular_pipeline: VernacularPipeline,
        approval_gate: ApprovalGate | None,
        publish_targets: list[PublishTarget],
    ) -> None:
        self.icp_agent = icp_agent
        self.vernacular_pipeline = vernacular_pipeline
        self.approval_gate = approval_gate
        self.seo_optimizer = SEOOptimizer()
        self.queue = PublishingQueue(publish_targets, approval_gate=approval_gate)
        self.scheduler = ContentScheduler(self.brief_from_icp)

    def brief_from_icp(self, icp: dict[str, Any], language_code: str, topic: str) -> ContentBrief:
        language = _normalize_language_code(language_code)
        if language not in SUPPORTED_LANGUAGES:
            language = "en"

        icp_payload = dict(icp or {})
        audience = str(
            icp_payload.get("target_audience") or icp_payload.get("segment") or "Growth operators"
        ).strip()
        pain_points = icp_payload.get("pain_points")
        if not isinstance(pain_points, list):
            pain_points = []

        prompt = (
            "Create a JSON content brief for SEO growth marketing article. "
            "Return keys: target_audience, keywords, tone, word_count_target.\n"
            f"Topic: {topic}\n"
            f"Audience: {audience}\n"
            f"Pain points: {pain_points}\n"
            "Use 5-8 search-intent keywords."
        )
        result = self.vernacular_pipeline.process(prompt, force_language=language)

        parsed = _extract_json_object(result.response_content)
        keywords = _ensure_keywords(
            parsed.get("keywords") if isinstance(parsed, dict) else None, topic, pain_points
        )
        tone = (
            str(parsed.get("tone") if isinstance(parsed, dict) else "").strip() or "helpful_expert"
        )

        word_target_raw = parsed.get("word_count_target") if isinstance(parsed, dict) else None
        try:
            word_count_target = int(word_target_raw)
        except (TypeError, ValueError):
            word_count_target = 1200
        word_count_target = max(600, min(2400, word_count_target))

        target_audience = (
            str(parsed.get("target_audience") if isinstance(parsed, dict) else "").strip()
            or audience
        )

        return ContentBrief(
            brief_id=_brief_id(),
            topic=str(topic or "").strip(),
            target_language=language,
            target_audience=target_audience,
            keywords=keywords,
            tone=tone,
            word_count_target=word_count_target,
        )

    def generate(self, brief: ContentBrief) -> ContentPiece:
        piece = ContentPiece.generate(
            brief,
            pipeline=self.vernacular_pipeline,
            topic_context={"keywords": brief.keywords, "tone": brief.tone},
        )

        linked_piece = self.seo_optimizer.add_internal_links(
            piece,
            {
                "ARCHON": "/product/archon",
                "automation": "/solutions/automation",
                "pipeline": "/solutions/pipeline",
            },
        )
        optimized = self.seo_optimizer.optimize(linked_piece, brief.keywords)
        return optimized.piece

    def schedule(
        self, topic: str, languages: list[str], icp: dict[str, Any], cadence_days: int = 7
    ) -> list[ContentBrief]:
        return self.scheduler.schedule(topic, languages, icp, cadence_days=cadence_days)

    def run_scheduled(self) -> list[ContentPiece]:
        generated: list[ContentPiece] = []
        now = datetime.now(timezone.utc)
        for entry in self.scheduler.due_entries(now=now):
            for language in entry.languages:
                brief = self.brief_from_icp(entry.icp, language, entry.topic)
                piece = self.generate(brief)
                self.queue.queue(piece)
                generated.append(piece)
            self.scheduler.advance(entry.schedule_id)
        return generated


def _run_maybe_awaitable(maybe_awaitable: Any) -> Any:
    if not asyncio.iscoroutine(maybe_awaitable):
        return maybe_awaitable
    try:
        asyncio.get_running_loop()
        # A running loop exists; fallback to explicit task wait for sync call sites.
        future = asyncio.ensure_future(maybe_awaitable)
        loop = asyncio.get_event_loop()
        while not future.done():
            loop.run_until_complete(asyncio.sleep(0))
        return future.result()
    except RuntimeError:
        return asyncio.run(maybe_awaitable)


def _article_prompt(brief: ContentBrief, topic_context: dict[str, Any]) -> str:
    return (
        "Write a complete SEO article in the requested language.\n"
        f"Topic: {brief.topic}\n"
        f"Target audience: {brief.target_audience}\n"
        f"Target language: {brief.target_language}\n"
        f"Keywords: {', '.join(brief.keywords)}\n"
        f"Tone: {brief.tone}\n"
        f"Word target: {brief.word_count_target}\n"
        f"Additional context: {topic_context}\n"
        "Structure requirements:\n"
        "- H1 title\n"
        "- Intro paragraph\n"
        "- 3 to 5 H2 sections\n"
        "- Conclusion\n"
        "- CTA that references ARCHON capability relevant to the topic"
    )


def _split_title_and_body(raw: str, topic: str) -> tuple[str, str]:
    text = str(raw or "").strip()
    if not text:
        return _fallback_title(topic), ""

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    title = ""
    body_lines: list[str] = []
    for index, line in enumerate(lines):
        if index == 0 and line.startswith("# "):
            title = line[2:].strip()
            continue
        if index == 0 and not line.startswith("## "):
            title = line.strip().lstrip("#").strip()
            continue
        body_lines.append(line)

    if not title:
        title = _fallback_title(topic)
    return title, "\n".join(body_lines).strip()


def _enforce_article_structure(raw_body: str, brief: ContentBrief) -> str:
    body = str(raw_body or "").strip()
    if not body:
        body = _fallback_article_body(brief)

    sections = re.findall(r"^##\s+", body, flags=re.MULTILINE)
    if len(sections) < 3:
        body = _fallback_article_body(brief)

    if "cta" not in body.lower() and "ARCHON" not in body:
        capability = _archon_capability_for_topic(brief.topic)
        body += (
            "\n\n## CTA\n"
            f"Explore how ARCHON {capability} to accelerate results for {brief.target_audience}."
        )

    return body


def _fallback_article_body(brief: ContentBrief) -> str:
    capability = _archon_capability_for_topic(brief.topic)
    keyword_text = ", ".join(brief.keywords[:5])
    return (
        f"{brief.topic} is a priority for teams focused on {brief.target_audience}. "
        f"This guide covers practical steps and search-intent themes including {keyword_text}.\n\n"
        f"## Understand the Core Challenge\n"
        f"Most teams struggle because execution and insight are disconnected across channels and languages.\n\n"
        f"## Build a Repeatable Process\n"
        f"Create a measurable workflow: define outcomes, map constraints, and iterate with explicit feedback loops.\n\n"
        f"## Measure What Moves the Outcome\n"
        f"Track lead indicators and lagging metrics so you can adjust quickly and preserve quality.\n\n"
        f"## Conclusion\n"
        f"Consistent content and operational clarity create durable growth when tied to real audience pain points.\n\n"
        f"## CTA\n"
        f"Use ARCHON to {capability} and execute multilingual content operations with less manual overhead."
    )


def _archon_capability_for_topic(topic: str) -> str:
    lowered = str(topic or "").lower()
    if any(token in lowered for token in ["seo", "content", "blog"]):
        return "plans, generates, and optimizes SEO content"
    if any(token in lowered for token in ["sales", "lead", "pipeline", "outreach"]):
        return "orchestrates outbound + follow-up workflows"
    if any(token in lowered for token in ["support", "chat", "webchat"]):
        return "deploys intelligent support and webchat automation"
    if any(token in lowered for token in ["translation", "language", "vernacular"]):
        return "reasons natively across 40+ languages"
    return "automates execution across planning, analysis, and delivery"


def _ensure_keywords(raw_keywords: Any, topic: str, pain_points: list[Any]) -> list[str]:
    keywords: list[str] = []

    if isinstance(raw_keywords, list):
        for item in raw_keywords:
            text = str(item or "").strip()
            if text:
                keywords.append(text)

    if not keywords:
        topic_terms = [token for token in re.split(r"[^\w]+", str(topic or "").lower()) if token]
        keywords.extend(topic_terms[:3])

    for pain in pain_points:
        text = str(pain or "").strip()
        if text:
            keywords.append(text)

    deduped: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        lowered = keyword.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(keyword)

    if not deduped:
        deduped = ["archon automation", "multilingual content", "seo strategy"]

    return deduped[:8]


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _normalize_language_code(language_code: str) -> str:
    text = str(language_code or "").strip().lower().replace("_", "-")
    return text.split("-", 1)[0] if text else "en"


def _fallback_title(topic: str) -> str:
    return str(topic or "Untitled").strip().title() or "Untitled"


def _slugify(title: str, language_code: str) -> str:
    language = _normalize_language_code(language_code)
    normalized = re.sub(r"[^a-zA-Z0-9\s-]", "", title).strip().lower()
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    if not normalized:
        normalized = f"article-{uuid.uuid4().hex[:8]}"
    return f"{language}-{normalized}"


def _meta_from_body(*, title: str, body: str) -> str:
    plain = re.sub(r"[#*`\[\]()_]", "", body)
    plain = re.sub(r"\s+", " ", plain).strip()
    seed = f"{title.strip()} - {plain}".strip()
    if len(seed) <= 155:
        return seed
    truncated = seed[:152].rstrip()
    return f"{truncated}..."


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", str(text or "").lower())


def _word_count(text: str) -> int:
    return len(_tokenize(text))


def _count_syllables(word: str) -> int:
    lowered = re.sub(r"[^a-z]", "", word.lower())
    if not lowered:
        return 1
    vowels = "aeiouy"
    count = 0
    previous_vowel = False
    for char in lowered:
        is_vowel = char in vowels
        if is_vowel and not previous_vowel:
            count += 1
        previous_vowel = is_vowel
    if lowered.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def _as_markdown(piece: ContentPiece) -> str:
    return (
        f"# {piece.title}\n\n"
        f"<!-- slug: {piece.slug} -->\n"
        f"<!-- language: {piece.language_code} -->\n"
        f"<!-- meta: {piece.meta_description} -->\n\n"
        f"{piece.body}\n"
    )
