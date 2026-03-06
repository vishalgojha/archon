"""Tests for community monitoring and gated response workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

import archon.agents.community.community_agent as community_mod
from archon.agents.community.community_agent import (
    CommunityAgent,
    CommunityPost,
    DraftResponse,
    HNCollector,
    RedditCollector,
    ResponseComposer,
    RSSCollector,
    SignalDetector,
)


@dataclass
class _FakeResponse:
    status_code: int
    payload: dict[str, Any] | None = None
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self.payload or {}


def _post(
    *,
    post_id: str,
    title: str,
    body: str,
    source: str = "reddit",
) -> CommunityPost:
    return CommunityPost(
        post_id=post_id,
        source=source,
        title=title,
        body=body,
        author="alice",
        url=f"https://example.com/{post_id}",
        created_at=1_700_000_000.0,
        score=12.0,
        comments=3,
    )


def test_signal_detector_scoring_and_pain_point_extraction() -> None:
    detector = SignalDetector(llm_scorer=lambda _post: 0.3)
    relevant_post = _post(
        post_id="p1",
        title="stuck in spreadsheet hell and doing this manually",
        body="We keep copy paste work every day and wish there was a tool.",
    )

    relevant = detector.detect(relevant_post)
    assert relevant.score > 0.4
    assert relevant.is_relevant is True
    assert detector.extract_pain_points(relevant_post)

    neutral_detector = SignalDetector(llm_scorer=lambda _post: 0.5)
    neutral_post = _post(
        post_id="p2",
        title="Question about weekly standup format",
        body="No tooling issue, just asking preferences.",
    )
    neutral = neutral_detector.detect(neutral_post)
    assert neutral.score < 0.4
    assert neutral.is_relevant is False


def test_reddit_collector_parses_mocked_api(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        assert "access_token" in url
        return _FakeResponse(status_code=200, payload={"access_token": "token-123"})

    def fake_get(url: str, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        assert "oauth.reddit.com" in url
        return _FakeResponse(
            status_code=200,
            payload={
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "abc",
                                "title": "Doing this manually every week",
                                "selftext": "copy paste all day",
                                "author": "user1",
                                "permalink": "/r/test/comments/abc",
                                "created_utc": 1700000000,
                                "score": 42,
                                "num_comments": 7,
                            }
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(community_mod.httpx, "post", fake_post)
    monkeypatch.setattr(community_mod.httpx, "get", fake_get)

    collector = RedditCollector(client_id="id", client_secret="secret", user_agent="agent")
    posts = collector.collect(["test"], limit=5)

    assert len(posts) == 1
    assert posts[0].post_id == "abc"
    assert posts[0].source == "reddit"
    assert posts[0].author == "user1"


def test_hn_collector_parses_algolia_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        assert "hn.algolia.com" in url
        return _FakeResponse(
            status_code=200,
            payload={
                "hits": [
                    {
                        "objectID": "999",
                        "title": "Automate this repetitive task",
                        "story_text": "Still doing this manually at work.",
                        "author": "hn_user",
                        "url": "https://news.ycombinator.com/item?id=999",
                        "created_at_i": 1700000100,
                        "points": 55,
                        "num_comments": 11,
                    }
                ]
            },
        )

    monkeypatch.setattr(community_mod.httpx, "get", fake_get)
    collector = HNCollector()
    posts = collector.collect("manual workflow", limit=3)

    assert len(posts) == 1
    assert posts[0].post_id == "999"
    assert posts[0].source == "hackernews"


def test_rss_collector_parses_minimal_rss_xml(monkeypatch: pytest.MonkeyPatch) -> None:
    rss_xml = """
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <item>
          <title>Tedious copy paste in reporting</title>
          <description>Doing this manually every week.</description>
          <link>https://example.com/post-1</link>
          <author>rss_author</author>
          <pubDate>Wed, 02 Oct 2002 13:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """

    def fake_get(url: str, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        assert "feed" in url
        return _FakeResponse(status_code=200, text=rss_xml)

    monkeypatch.setattr(community_mod.httpx, "get", fake_get)
    collector = RSSCollector()
    posts = collector.collect(["https://example.com/feed.xml"], limit=5)

    assert len(posts) == 1
    assert posts[0].source == "rss"
    assert posts[0].title == "Tedious copy paste in reporting"


def test_response_composer_helpful_tone_and_archon_mention_logic() -> None:
    composer = ResponseComposer()

    relevant_post = _post(
        post_id="r1",
        title="Doing this manually is killing us",
        body="Copy paste workflows are too much time.",
    )
    relevant = composer.compose(relevant_post, ["doing this manually", "copy paste workflows"])

    assert isinstance(relevant, DraftResponse)
    assert relevant.body.strip()
    assert relevant.tone == "helpful_expert"
    assert not relevant.body.lstrip().startswith("ARCHON")
    assert relevant.includes_archon_mention is True

    neutral_post = _post(
        post_id="r2", title="Question about naming conventions", body="No pain point here."
    )
    neutral = composer.compose(neutral_post, [])
    assert neutral.includes_archon_mention is False


class _StaticCollector:
    def __init__(self, posts: list[CommunityPost]) -> None:
        self.posts = posts

    def collect(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return list(self.posts)


class _Gate:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def check(self, action: str, context: dict[str, Any], action_id: str) -> str:
        self.calls.append({"action": action, "context": context, "action_id": action_id})
        if context.get("post_id") == "deny-me":
            raise RuntimeError("denied")
        return action_id


def test_community_agent_run_relevant_irrelevant_and_gate_flow() -> None:
    detector = SignalDetector(llm_scorer=lambda _post: 0.3)
    gate = _Gate()
    published: list[str] = []

    posts = [
        _post(
            post_id="approve-me",
            title="spreadsheet hell and doing this manually",
            body="copy paste all day, wish there was a tool",
        ),
        _post(
            post_id="deny-me",
            title="spreadsheet hell and doing this manually",
            body="copy paste all day, wish there was a tool",
        ),
        _post(
            post_id="skip-me",
            title="Question about meeting templates",
            body="No workflow pain here",
        ),
    ]

    agent = CommunityAgent(
        detector=detector,
        reddit_collector=_StaticCollector(posts),
        hn_collector=_StaticCollector([]),
        rss_collector=_StaticCollector([]),
        composer=ResponseComposer(),
        approval_gate=gate,
        publisher=lambda post, draft: published.append(f"{post.post_id}:{len(draft.body)}"),
    )

    results = agent.run({"reddit": {"subreddits": ["automation"]}})
    by_post = {row.post_id: row for row in results}

    assert by_post["approve-me"].action_taken == "responded"
    assert by_post["approve-me"].approved is True

    assert by_post["deny-me"].action_taken == "approval_denied"
    assert by_post["deny-me"].approved is False

    assert by_post["skip-me"].action_taken == "skipped_irrelevant"
    assert by_post["skip-me"].approved is False

    # Gate should be called once per relevant post.
    assert len(gate.calls) == 2
    assert all(call["action"] == "send_message" for call in gate.calls)

    # Denied posts are not published.
    assert len(published) == 1
    assert published[0].startswith("approve-me:")
