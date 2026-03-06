"""Tests for federation peer discovery, pattern sharing, and consensus."""

from __future__ import annotations

import asyncio
import random
import time

import pytest

from archon.federation.consensus import ConsensusVote, HiveConsensus
from archon.federation.pattern_sharing import PatternSharer, PatternStore, WorkflowPattern
from archon.federation.peer_discovery import Peer, PeerRegistry


class _FakeHTTPResponse:
    def __init__(self, status_code: int = 200, payload: dict[str, object] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict[str, object]:
        return dict(self._payload)


class _RegistryClient:
    posts: list[tuple[str, dict[str, object]]] = []

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        del args, kwargs

    async def post(self, url: str, json: dict[str, object]):  # type: ignore[no-untyped-def]
        self.__class__.posts.append((url, json))
        return _FakeHTTPResponse(200, {})

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_peer_registry_register_heartbeat_discover_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import archon.federation.peer_discovery as module

    _RegistryClient.posts = []
    monkeypatch.setattr(module.httpx, "AsyncClient", _RegistryClient)
    registry = PeerRegistry(production_mode=True)
    try:
        now = time.time()
        peer_a = Peer(
            peer_id="peer-a",
            address="https://peer-a.example.com",
            public_key="pk-a",
            last_seen=now,
            capabilities=["growth", "debate"],
            version="1.0",
        )
        peer_b = Peer(
            peer_id="peer-b",
            address="https://peer-b.example.com",
            public_key="pk-b",
            last_seen=now - 700,  # stale
            capabilities=["vision"],
            version="1.0",
        )
        await registry.register(peer_a)
        await registry.register(peer_b)
        assert len(await registry.discover(None)) == 2

        growth_peers = await registry.discover("growth")
        assert [peer.peer_id for peer in growth_peers] == ["peer-a"]

        await registry.heartbeat("peer-a")
        remaining = await registry.discover(None)
        assert [peer.peer_id for peer in remaining] == ["peer-a"]  # peer-b removed as stale

        # Registering peer-b triggers announce broadcast to peer-a.
        assert any(url.endswith("/federation/announce") for url, _ in _RegistryClient.posts)

        with pytest.raises(ValueError):
            await registry.register(
                Peer(
                    peer_id="bad",
                    address="ftp://bad.example.com",
                    public_key="pk",
                    last_seen=now,
                    capabilities=[],
                    version="1.0",
                )
            )
        with pytest.raises(ValueError):
            await registry.register(
                Peer(
                    peer_id="local",
                    address="http://localhost:8080",
                    public_key="pk",
                    last_seen=now,
                    capabilities=[],
                    version="1.0",
                )
            )
    finally:
        await registry.aclose()


def test_pattern_sharer_privatize_noise_scale_receive_clip_and_merge() -> None:
    rng_a = random.Random(11)
    rng_b = random.Random(11)
    pattern = WorkflowPattern(
        pattern_id="p1",
        workflow_type="growth",
        step_sequence=["a", "b", "c"],
        avg_score=0.8,
        sample_count=100,
    )
    sharer_a = PatternSharer(rng=rng_a)
    sharer_b = PatternSharer(rng=rng_b)
    noisy_hi_eps = sharer_a.privatize(pattern, epsilon=2.0)
    noisy_lo_eps = sharer_b.privatize(pattern, epsilon=0.25)

    assert noisy_hi_eps.avg_score != pattern.avg_score or noisy_hi_eps.sample_count != pattern.sample_count
    diff_hi = abs(noisy_hi_eps.avg_score - pattern.avg_score)
    diff_lo = abs(noisy_lo_eps.avg_score - pattern.avg_score)
    assert diff_lo >= diff_hi  # lower epsilon => higher expected noise scale

    store = PatternStore()
    sharer = PatternSharer(pattern_store=store)
    clipped = asyncio.run(
        sharer.receive(
            {
                "pattern_id": "clip",
                "workflow_type": "debate",
                "step_sequence": ["x"],
                "avg_score": 9.0,
                "sample_count": -50,
            }
        )
    )
    assert clipped.avg_score == 1.0
    assert clipped.sample_count == 1

    first = asyncio.run(
        sharer.receive(
            {
                "pattern_id": "known",
                "workflow_type": "growth",
                "step_sequence": ["a"],
                "avg_score": 0.2,
                "sample_count": 10,
            }
        )
    )
    second = asyncio.run(
        sharer.receive(
            {
                "pattern_id": "known",
                "workflow_type": "growth",
                "step_sequence": ["a", "b"],
                "avg_score": 0.8,
                "sample_count": 30,
            }
        )
    )
    assert first.pattern_id == second.pattern_id == "known"
    assert second.avg_score == pytest.approx(0.5, abs=1e-6)
    assert second.sample_count == 20


class _ConsensusClient:
    responses: dict[str, _FakeHTTPResponse] = {}
    calls: list[str] = []

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        del args, kwargs

    async def post(self, url: str, json: dict[str, object], timeout: float = 30):  # type: ignore[no-untyped-def]
        del json, timeout
        self.__class__.calls.append(url)
        return self.responses.get(url) or _FakeHTTPResponse(500, {})

    async def aclose(self) -> None:
        return None


def test_hive_consensus_borda_and_reputation_updates() -> None:
    consensus = HiveConsensus()
    votes = [
        ConsensusVote(voter_id="p1", option="A", weight=1.0, reasoning=""),
        ConsensusVote(voter_id="p2", option="B", weight=2.0, reasoning=""),
    ]
    scores = consensus._borda_scores(votes, ["A", "B", "C"])  # noqa: SLF001
    assert scores["B"] > scores["A"] > scores["C"]

    assert consensus.update_reputation("p1", True) == pytest.approx(1.1, abs=1e-6)
    assert consensus.update_reputation("p1", False) == pytest.approx(1.05, abs=1e-6)
    for _ in range(30):
        value = consensus.update_reputation("p2", False)
    assert value >= 0.1


@pytest.mark.asyncio
async def test_hive_consensus_quorum_and_request_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    import archon.federation.consensus as module

    _ConsensusClient.calls = []
    _ConsensusClient.responses = {
        "https://peer-1.example.com/federation/consensus": _FakeHTTPResponse(
            200, {"option": "A", "reasoning": "best"}
        ),
        "https://peer-2.example.com/federation/consensus": _FakeHTTPResponse(
            200, {"option": "B", "reasoning": "second"}
        ),
        "https://peer-3.example.com/federation/consensus": _FakeHTTPResponse(500, {}),
    }
    monkeypatch.setattr(module.httpx, "AsyncClient", _ConsensusClient)

    consensus = HiveConsensus(requester_id="local")
    try:
        peers = [
            {"peer_id": "p1", "address": "https://peer-1.example.com"},
            {"peer_id": "p2", "address": "https://peer-2.example.com"},
            {"peer_id": "p3", "address": "https://peer-3.example.com"},
        ]
        result = await consensus.request_consensus("Pick", ["A", "B"], peers, timeout_s=1)
        assert result.winning_option in {"A", "B"}
        assert len(result.participating_peers) == 2
        assert result.vote_counts

        # quorum fail: 1/3 < 51%
        _ConsensusClient.responses["https://peer-2.example.com/federation/consensus"] = _FakeHTTPResponse(500, {})
        no_quorum = await consensus.request_consensus("Pick", ["A", "B"], peers, timeout_s=1)
        assert no_quorum.winning_option == "no_quorum"
        assert no_quorum.confidence == 0.0
    finally:
        await consensus.aclose()
