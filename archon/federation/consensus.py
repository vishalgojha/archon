"""Federated weighted-vote consensus with quorum and reputation."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(slots=True, frozen=True)
class ConsensusRequest:
    """Consensus request payload."""

    question: str
    options: list[str]
    requester_id: str


@dataclass(slots=True, frozen=True)
class ConsensusVote:
    """One peer vote used in weighted consensus."""

    voter_id: str
    option: str
    weight: float
    reasoning: str


@dataclass(slots=True, frozen=True)
class ConsensusResult:
    """Aggregated consensus output."""

    winning_option: str
    vote_counts: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    participating_peers: list[str] = field(default_factory=list)


class HiveConsensus:
    """Weighted Borda-style consensus coordinator for federation peers."""

    def __init__(self, *, requester_id: str = "local", timeout_seconds: float = 5.0) -> None:
        self.requester_id = requester_id
        self._client = httpx.AsyncClient(timeout=timeout_seconds)
        self._reputation: dict[str, float] = {}

    async def aclose(self) -> None:
        """Close outbound HTTP resources."""

        await self._client.aclose()

    async def request_consensus(
        self,
        question: str,
        options: list[str],
        peers: list[Any],
        timeout_s: float = 30,
    ) -> ConsensusResult:
        """Broadcast consensus request and aggregate weighted votes."""

        normalized_options = [str(item) for item in options]
        if not normalized_options:
            raise ValueError("Consensus options cannot be empty.")

        peer_targets = [_normalize_peer_descriptor(peer) for peer in peers]
        peer_targets = [target for target in peer_targets if target is not None]
        invited_count = len(peer_targets)
        if invited_count == 0:
            return ConsensusResult(
                winning_option="no_quorum", vote_counts={}, confidence=0.0, participating_peers=[]
            )

        request = ConsensusRequest(
            question=question, options=normalized_options, requester_id=self.requester_id
        )
        tasks = [
            asyncio.create_task(self._request_vote(peer_id, address, request, timeout_s))
            for peer_id, address in peer_targets
        ]
        votes_raw = await asyncio.gather(*tasks)
        votes = [vote for vote in votes_raw if vote is not None]

        quorum_needed = math.ceil(invited_count * 0.51)
        if len(votes) < quorum_needed:
            return ConsensusResult(
                winning_option="no_quorum",
                vote_counts={},
                confidence=0.0,
                participating_peers=[vote.voter_id for vote in votes],
            )

        vote_counts = self._borda_scores(votes, normalized_options)
        winning_option = max(vote_counts.items(), key=lambda row: row[1])[0]
        total_points = sum(vote_counts.values())
        confidence = (vote_counts[winning_option] / total_points) if total_points > 0 else 0.0
        return ConsensusResult(
            winning_option=winning_option,
            vote_counts=vote_counts,
            confidence=round(confidence, 6),
            participating_peers=[vote.voter_id for vote in votes],
        )

    def update_reputation(self, peer_id: str, was_correct: bool) -> float:
        """Update peer reputation: correct +0.1, incorrect -0.05 (min 0.1)."""

        current = self._reputation.get(peer_id, 1.0)
        current += 0.1 if was_correct else -0.05
        current = max(0.1, current)
        self._reputation[peer_id] = round(current, 6)
        return self._reputation[peer_id]

    def _borda_scores(self, votes: list[ConsensusVote], options: list[str]) -> dict[str, float]:
        counts = {option: 0.0 for option in options}
        points_for_first = max(1, len(options) - 1)
        for vote in votes:
            if vote.option not in counts:
                continue
            counts[vote.option] += vote.weight * points_for_first
        return {key: round(value, 6) for key, value in counts.items()}

    async def _request_vote(
        self,
        peer_id: str,
        address: str,
        request: ConsensusRequest,
        timeout_s: float,
    ) -> ConsensusVote | None:
        payload = {
            "question": request.question,
            "options": request.options,
            "requester_id": request.requester_id,
        }
        try:
            response = await self._client.post(
                f"{address.rstrip('/')}/federation/consensus",
                json=payload,
                timeout=timeout_s,
            )
            if response.status_code >= 400:
                return None
            data = response.json()
            option = str(data.get("option", ""))
            if option not in request.options:
                return None
            weight = self._reputation.get(peer_id, 1.0)
            reasoning = str(data.get("reasoning", ""))
            return ConsensusVote(
                voter_id=peer_id, option=option, weight=weight, reasoning=reasoning
            )
        except Exception:
            return None


def _normalize_peer_descriptor(peer: Any) -> tuple[str, str] | None:
    if isinstance(peer, dict):
        peer_id = str(peer.get("peer_id") or peer.get("id") or peer.get("address") or "")
        address = str(peer.get("address") or "")
    else:
        peer_id = str(
            getattr(peer, "peer_id", "") or getattr(peer, "id", "") or getattr(peer, "address", "")
        )
        address = str(getattr(peer, "address", ""))
    if not peer_id or not address:
        return None
    return peer_id, address
