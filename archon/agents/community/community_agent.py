"""Community monitoring and helpful response automation for manual-work complaints."""

from __future__ import annotations

import asyncio
import email.utils
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from xml.etree import ElementTree

import httpx

from archon.core.approval_gate import ApprovalGate
from archon.providers import ProviderRouter


@dataclass(slots=True)
class CommunityPost:
    post_id: str
    source: str
    title: str
    body: str
    author: str
    url: str
    created_at: float
    score: float
    comments: int


@dataclass(slots=True)
class DetectionResult:
    is_relevant: bool
    pain_points: list[str]
    score: float
    signals: dict[str, Any]


@dataclass(slots=True)
class DraftResponse:
    post_id: str
    body: str
    tone: str
    includes_archon_mention: bool
    cta_type: str


@dataclass(slots=True)
class ActionResult:
    post_id: str
    source: str
    action_taken: str
    response_body: str
    approved: bool


class SignalDetector:
    """Detects manual-work pain signals using keywords + optional LLM scoring."""

    manual_work_keywords = [
        "doing this manually",
        "spreadsheet hell",
        "copy paste",
        "automate this",
        "too much time",
        "tedious",
        "repetitive task",
        "no api",
        "wish there was a tool",
    ]

    def __init__(
        self,
        router: ProviderRouter | None = None,
        *,
        llm_role: str = "fast",
        llm_scorer: Callable[[CommunityPost], float] | None = None,
    ) -> None:
        self.router = router
        self.llm_role = llm_role
        self.llm_scorer = llm_scorer

    def detect(self, post: CommunityPost) -> DetectionResult:
        text = f"{post.title}\n{post.body}".lower()
        matches = [keyword for keyword in self.manual_work_keywords if keyword in text]
        keyword_score = min(1.0, len(matches) * 0.1)

        llm_score = self._llm_relevance_score(post)
        score = min(1.0, keyword_score + (llm_score * 0.5))

        pain_points = self.extract_pain_points(post) if score > 0.4 else []
        return DetectionResult(
            is_relevant=score > 0.4,
            pain_points=pain_points,
            score=round(score, 4),
            signals={
                "keyword_hits": len(matches),
                "keyword_matches": matches,
                "keyword_score": round(keyword_score, 4),
                "llm_score": round(llm_score, 4),
            },
        )

    def extract_pain_points(self, post: CommunityPost) -> list[str]:
        content = f"{post.title}. {post.body}".strip()
        if not content:
            return []

        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", content) if item.strip()]
        points: list[str] = []
        for sentence in sentences:
            lower = sentence.lower()
            if any(keyword in lower for keyword in self.manual_work_keywords):
                points.append(sentence)

        if points:
            return points[:6]

        # Fallback: capture pain-like wording even without exact keyword phrase.
        fallback_tokens = [
            "manual",
            "repetitive",
            "time",
            "copy",
            "spreadsheet",
            "tedious",
            "automation",
        ]
        for sentence in sentences:
            lower = sentence.lower()
            if any(token in lower for token in fallback_tokens):
                points.append(sentence)
        return points[:4]

    def _llm_relevance_score(self, post: CommunityPost) -> float:
        if self.llm_scorer is not None:
            return _clamp_score(self.llm_scorer(post))

        if self.router is None:
            return 0.0

        prompt = (
            "Score relevance from 0 to 1 for whether this post describes painful manual work that could be automated. "
            'Return JSON only: {"score": 0.0}.\n'
            f"Title: {post.title}\n"
            f"Body: {post.body[:1000]}"
        )
        text = _invoke_router_text(self.router, role=self.llm_role, prompt=prompt)
        if not text:
            return 0.0

        parsed = _extract_json(text)
        if parsed and "score" in parsed:
            return _clamp_score(parsed["score"])

        maybe_number = re.findall(r"\d*\.\d+|\d+", text)
        if maybe_number:
            return _clamp_score(float(maybe_number[0]))
        return 0.0


class RedditCollector:
    """Collects Reddit posts via direct OAuth API."""

    token_url = "https://www.reddit.com/api/v1/access_token"
    oauth_base = "https://oauth.reddit.com"

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.user_agent = user_agent or "archon-community-agent/1.0"

    def collect(self, subreddits: list[str], limit: int = 25) -> list[CommunityPost]:
        token = self._fetch_access_token()
        if not token:
            return []

        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": self.user_agent,
        }
        posts: list[CommunityPost] = []
        for subreddit in subreddits:
            sub = str(subreddit or "").strip()
            if not sub:
                continue
            url = f"{self.oauth_base}/r/{sub}/new.json?limit={int(limit)}"
            response = httpx.get(url, headers=headers, timeout=15.0)
            if response.status_code >= 400:
                continue
            payload = response.json()
            for child in payload.get("data", {}).get("children", []):
                data = child.get("data", {})
                posts.append(
                    CommunityPost(
                        post_id=str(data.get("id") or ""),
                        source="reddit",
                        title=str(data.get("title") or "").strip(),
                        body=str(data.get("selftext") or "").strip(),
                        author=str(data.get("author") or "").strip(),
                        url=f"https://reddit.com{data.get('permalink', '')}",
                        created_at=float(data.get("created_utc") or _now()),
                        score=float(data.get("score") or 0.0),
                        comments=int(data.get("num_comments") or 0),
                    )
                )
        return posts

    def _fetch_access_token(self) -> str:
        if not self.client_id or not self.client_secret:
            return ""

        response = httpx.post(
            self.token_url,
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": self.user_agent},
            timeout=15.0,
        )
        if response.status_code >= 400:
            return ""
        payload = response.json()
        return str(payload.get("access_token") or "").strip()


class HNCollector:
    """Collects Hacker News stories through Algolia search API."""

    endpoint = "https://hn.algolia.com/api/v1/search"

    def collect(self, query: str, limit: int = 25) -> list[CommunityPost]:
        response = httpx.get(
            self.endpoint,
            params={
                "query": str(query or "").strip(),
                "tags": "story",
                "hitsPerPage": int(limit),
            },
            timeout=15.0,
        )
        if response.status_code >= 400:
            return []

        payload = response.json()
        posts: list[CommunityPost] = []
        for hit in payload.get("hits", []):
            posts.append(
                CommunityPost(
                    post_id=str(hit.get("objectID") or ""),
                    source="hackernews",
                    title=str(hit.get("title") or "").strip(),
                    body=str(hit.get("story_text") or "").strip(),
                    author=str(hit.get("author") or "").strip(),
                    url=str(hit.get("url") or hit.get("story_url") or "").strip(),
                    created_at=float(hit.get("created_at_i") or _now()),
                    score=float(hit.get("points") or 0.0),
                    comments=int(hit.get("num_comments") or 0),
                )
            )
        return posts


class RSSCollector:
    """Collects posts from RSS or Atom feeds using stdlib XML parsing."""

    def collect(self, feed_urls: list[str], limit: int = 25) -> list[CommunityPost]:
        posts: list[CommunityPost] = []
        max_items = max(1, int(limit))

        for feed_url in feed_urls:
            url = str(feed_url or "").strip()
            if not url:
                continue
            if len(posts) >= max_items:
                break

            response = httpx.get(url, timeout=15.0)
            if response.status_code >= 400:
                continue

            try:
                root = ElementTree.fromstring(response.text)
            except ElementTree.ParseError:
                continue

            items = self._rss_items(root) + self._atom_entries(root)
            for item in items:
                posts.append(item)
                if len(posts) >= max_items:
                    break

        return posts

    def _rss_items(self, root: ElementTree.Element) -> list[CommunityPost]:
        rows: list[CommunityPost] = []
        for index, item in enumerate(root.findall(".//item")):
            title = _text(item.find("title"))
            body = _text(item.find("description"))
            link = _text(item.find("link"))
            author = _text(item.find("author"))
            created = _parse_datetime(_text(item.find("pubDate")))

            seed = f"rss|{link}|{title}|{index}"
            post_id = hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:16]
            rows.append(
                CommunityPost(
                    post_id=post_id,
                    source="rss",
                    title=title,
                    body=body,
                    author=author,
                    url=link,
                    created_at=created,
                    score=0.0,
                    comments=0,
                )
            )
        return rows

    def _atom_entries(self, root: ElementTree.Element) -> list[CommunityPost]:
        rows: list[CommunityPost] = []
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for index, entry in enumerate(root.findall(".//a:entry", ns)):
            title = _text(entry.find("a:title", ns))
            body = _text(entry.find("a:summary", ns)) or _text(entry.find("a:content", ns))
            author = _text(entry.find("a:author/a:name", ns))
            updated = _text(entry.find("a:updated", ns))
            link_node = entry.find("a:link[@rel='alternate']", ns) or entry.find("a:link", ns)
            link = link_node.get("href", "").strip() if link_node is not None else ""

            seed = f"atom|{link}|{title}|{index}"
            post_id = hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:16]
            rows.append(
                CommunityPost(
                    post_id=post_id,
                    source="rss",
                    title=title,
                    body=body,
                    author=author,
                    url=link,
                    created_at=_parse_datetime(updated),
                    score=0.0,
                    comments=0,
                )
            )
        return rows


class ResponseComposer:
    """Composes non-salesy helpful draft responses for communities."""

    def compose(self, post: CommunityPost, pain_points: list[str]) -> DraftResponse:
        source = post.source.lower()
        is_relevant = bool(pain_points)
        includes_archon = is_relevant and _is_archon_directly_relevant(post, pain_points)

        lead = (
            "You are not alone here; this usually happens when repetitive ops outgrow the original process."
            if is_relevant
            else "A practical first step is to map the workflow and identify where handoffs fail."
        )

        tactics = (
            "A reliable approach is to standardize one input format, add lightweight validation, "
            "and remove copy/paste by routing updates through one automation path."
        )

        pain_summary = (
            f"From your post, the main friction points seem to be: {', '.join(pain_points[:3])}."
            if pain_points
            else ""
        )

        cta_paragraph = ""
        cta_type = "none"
        if includes_archon:
            cta_type = "soft_mention"
            cta_paragraph = (
                "If useful, ARCHON can help orchestrate this flow with multilingual reasoning and approval-gated actions "
                "so you reduce manual toil without losing control."
            )

        paragraphs = [lead, tactics]
        if pain_summary:
            paragraphs.append(pain_summary)
        if cta_paragraph:
            paragraphs.append(cta_paragraph)

        paragraphs = paragraphs[:4]
        if len(paragraphs) < 2:
            paragraphs.append(
                "If you want, I can outline a concrete migration path from manual to semi-automated."
            )

        if source == "reddit":
            body = "\n\n".join(paragraphs)
        else:
            body = "\n\n".join(paragraphs)

        return DraftResponse(
            post_id=post.post_id,
            body=body.strip(),
            tone="helpful_expert",
            includes_archon_mention=includes_archon,
            cta_type=cta_type,
        )


class CommunityAgent:
    """Collects, detects, drafts, gates, and publishes community responses."""

    def __init__(
        self,
        *,
        detector: SignalDetector | None = None,
        reddit_collector: RedditCollector | None = None,
        hn_collector: HNCollector | None = None,
        rss_collector: RSSCollector | None = None,
        composer: ResponseComposer | None = None,
        approval_gate: ApprovalGate | Any | None = None,
        publisher: Callable[[CommunityPost, DraftResponse], Any] | None = None,
        event_sink=None,
    ) -> None:
        self.detector = detector or SignalDetector()
        self.reddit_collector = reddit_collector or RedditCollector()
        self.hn_collector = hn_collector or HNCollector()
        self.rss_collector = rss_collector or RSSCollector()
        self.composer = composer or ResponseComposer()
        self.approval_gate = approval_gate
        self.publisher = publisher
        self.event_sink = event_sink

    def run(self, sources_config: dict[str, Any]) -> list[ActionResult]:
        posts = self._collect_posts(sources_config)
        results: list[ActionResult] = []

        for post in posts:
            detection = self.detector.detect(post)
            if not detection.is_relevant:
                results.append(
                    ActionResult(
                        post_id=post.post_id,
                        source=post.source,
                        action_taken="skipped_irrelevant",
                        response_body="",
                        approved=False,
                    )
                )
                continue

            draft = self.composer.compose(post, detection.pain_points)
            approved = self._gate_response(post, draft)
            if not approved:
                results.append(
                    ActionResult(
                        post_id=post.post_id,
                        source=post.source,
                        action_taken="approval_denied",
                        response_body=draft.body,
                        approved=False,
                    )
                )
                continue

            self._publish(post, draft, sources_config)
            results.append(
                ActionResult(
                    post_id=post.post_id,
                    source=post.source,
                    action_taken="responded",
                    response_body=draft.body,
                    approved=True,
                )
            )

        return results

    def _collect_posts(self, sources_config: dict[str, Any]) -> list[CommunityPost]:
        posts: list[CommunityPost] = []

        reddit_cfg = sources_config.get("reddit") or {}
        subreddits = reddit_cfg.get("subreddits") or []
        if subreddits:
            posts.extend(
                self.reddit_collector.collect(
                    list(subreddits), limit=int(reddit_cfg.get("limit", 25))
                )
            )

        hn_cfg = sources_config.get("hn") or {}
        query = str(hn_cfg.get("query") or "").strip()
        if query:
            posts.extend(self.hn_collector.collect(query=query, limit=int(hn_cfg.get("limit", 25))))

        rss_cfg = sources_config.get("rss") or {}
        feeds = rss_cfg.get("feed_urls") or []
        if feeds:
            posts.extend(
                self.rss_collector.collect(list(feeds), limit=int(rss_cfg.get("limit", 25)))
            )

        return posts

    def _gate_response(self, post: CommunityPost, draft: DraftResponse) -> bool:
        if self.approval_gate is None:
            return False

        action_id = f"community-{post.source}-{post.post_id}"
        context = {
            "post_id": post.post_id,
            "source": post.source,
            "url": post.url,
            "response_preview": draft.body[:220],
            "event_sink": self.event_sink,
        }

        try:
            maybe = self.approval_gate.check(
                action="send_message", context=context, action_id=action_id
            )
            _run_maybe_awaitable(maybe)
            return True
        except Exception:
            return False

    def _publish(
        self, post: CommunityPost, draft: DraftResponse, sources_config: dict[str, Any]
    ) -> None:
        source_publishers = (
            sources_config.get("publishers") if isinstance(sources_config, dict) else None
        )
        if isinstance(source_publishers, dict):
            callback = source_publishers.get(post.source)
            if callable(callback):
                callback(post, draft)
                return

        callback = sources_config.get("publisher") if isinstance(sources_config, dict) else None
        if callable(callback):
            callback(post, draft)
            return

        if callable(self.publisher):
            self.publisher(post, draft)


def _run_maybe_awaitable(value: Any) -> Any:
    if not asyncio.iscoroutine(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    # Synchronous caller with a running loop cannot safely block; fail closed.
    raise RuntimeError("Cannot synchronously wait for approval while event loop is running.")


def _text(node: ElementTree.Element | None) -> str:
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def _parse_datetime(raw: str) -> float:
    text = str(raw or "").strip()
    if not text:
        return _now()

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        pass

    try:
        parsed_email = email.utils.parsedate_to_datetime(text)
        if parsed_email is not None:
            if parsed_email.tzinfo is None:
                parsed_email = parsed_email.replace(tzinfo=timezone.utc)
            return parsed_email.timestamp()
    except Exception:
        pass
    return _now()


def _clamp_score(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))


def _extract_json(text: str) -> dict[str, Any] | None:
    blob = str(text or "").strip()
    if not blob:
        return None

    try:
        parsed = json.loads(blob)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = blob.find("{")
    end = blob.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(blob[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _invoke_router_text(router: ProviderRouter, *, role: str, prompt: str) -> str:
    try:
        asyncio.get_running_loop()
        return ""
    except RuntimeError:
        pass

    try:
        response = asyncio.run(
            router.invoke(
                role=role,
                prompt=prompt,
                system_prompt="You are classifying manual-work problem relevance.",
            )
        )
    except Exception:
        return ""
    return str(getattr(response, "text", "") or "").strip()


def _is_archon_directly_relevant(post: CommunityPost, pain_points: list[str]) -> bool:
    text = f"{post.title}\n{post.body}\n" + "\n".join(pain_points)
    lowered = text.lower()
    triggers = [
        "manual",
        "automate",
        "repetitive",
        "copy paste",
        "workflow",
        "no api",
        "too much time",
        "tool",
    ]
    return any(token in lowered for token in triggers)


def _now() -> float:
    return time.time()
