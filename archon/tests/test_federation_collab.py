"""Tests for cross-instance federation broker, orchestrator wrapper, and API endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import jwt
import pytest

from archon.core.orchestrator import OrchestrationResult
from archon.federation.collab import (
    BidResponse,
    CollabOrchestrator,
    FederatedResult,
    FederatedTask,
    TaskBroker,
)
from archon.federation.peer_discovery import Peer
from archon.interfaces.api.server import app
from archon.testing.asgi import lifespan, request


@pytest.fixture(autouse=True)
def _env_fixture() -> None:
    previous_router_key = os.environ.get("OPENROUTER_API_KEY")
    previous_jwt = os.environ.get("ARCHON_JWT_SECRET")
    os.environ["OPENROUTER_API_KEY"] = previous_router_key or "federation-test-openrouter-key"
    os.environ["ARCHON_JWT_SECRET"] = previous_jwt or "archon-dev-secret-change-me-32-bytes"
    try:
        yield
    finally:
        if previous_router_key is None:
            os.environ.pop("OPENROUTER_API_KEY", None)
        else:
            os.environ["OPENROUTER_API_KEY"] = previous_router_key
        if previous_jwt is None:
            os.environ.pop("ARCHON_JWT_SECRET", None)
        else:
            os.environ["ARCHON_JWT_SECRET"] = previous_jwt


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self) -> dict[str, Any]:
        return dict(self._payload)


class _FakeClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, json: dict[str, Any], timeout: float = 30.0):  # type: ignore[no-untyped-def]
        del timeout
        self.posts.append((url, dict(json)))
        if url.endswith("/federation/tasks/bid"):
            peer_tag = "peer-a" if "peer-a" in url else "peer-b"
            if peer_tag == "peer-a":
                return _FakeResponse(
                    200,
                    {
                        "peer_id": "peer-a",
                        "can_fulfill": True,
                        "estimated_cost_usd": 0.2,
                        "estimated_time_s": 7.0,
                        "confidence": 0.8,
                    },
                )
            return _FakeResponse(
                200,
                {
                    "peer_id": "peer-b",
                    "can_fulfill": True,
                    "estimated_cost_usd": 0.1,
                    "estimated_time_s": 5.0,
                    "confidence": 0.9,
                },
            )
        if url.endswith("/federation/tasks/execute"):
            return _FakeResponse(
                200,
                {"result": "delegated-answer", "cost_usd": 0.11, "time_s": 2.5, "success": True},
            )
        return _FakeResponse(500, {})

    async def aclose(self) -> None:
        return None


class _RecordingGate:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def check(self, action: str, context: dict[str, Any], action_id: str) -> str:
        self.calls.append({"action": action, "context": dict(context), "action_id": action_id})
        return action_id


@dataclass
class _MemoryStore:
    merged: list[dict[str, Any]]

    async def add_entry(self, **kwargs: Any) -> int:  # noqa: ANN401
        self.merged.append(dict(kwargs))
        return 1


class _LocalOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.memory_store = _MemoryStore(merged=[])

    async def execute(self, *, goal: str, mode: str, context: dict[str, Any]):  # type: ignore[no-untyped-def]
        self.calls.append({"goal": goal, "mode": mode, "context": dict(context)})
        return SimpleNamespace(final_answer=f"local:{goal}")


def _peer(peer_id: str) -> Peer:
    return Peer(
        peer_id=peer_id,
        address=f"https://{peer_id}.example.com",
        public_key=f"pk-{peer_id}",
        last_seen=time.time(),
        capabilities=["analysis"],
        version="1.0",
    )


def _auth_headers(tenant: str = "tenant-fed") -> dict[str, str]:
    token = jwt.encode(
        {"sub": tenant, "tier": "enterprise"},
        "archon-dev-secret-change-me-32-bytes",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_task_broker_advertise_calls_all_peers_and_selects_lowest_composite() -> None:
    client = _FakeClient()
    gate = _RecordingGate()
    broker = TaskBroker(client=client, approval_gate=gate)
    task = FederatedTask(
        task_id="task-1",
        description="Need external capability",
        required_capabilities=["vision"],
        requester_instance_id="local",
        deadline_s=10.0,
        context={},
    )
    peers = [_peer("peer-a"), _peer("peer-b")]

    bids = await broker.advertise(task, peers)
    assert len(bids) == 2
    assert len([url for url, _payload in client.posts if url.endswith("/bid")]) == 2
    assert len(gate.calls) == 2

    winner = broker.select_peer(bids)
    assert winner is not None
    assert winner.peer_id == "peer-b"


def test_task_broker_select_peer_returns_none_when_no_peer_can_fulfill() -> None:
    broker = TaskBroker(client=_FakeClient(), approval_gate=_RecordingGate())
    winner = broker.select_peer(
        [
            BidResponse("peer-a", False, 1.0, 1.0, 0.5),
            BidResponse("peer-b", False, 0.1, 0.2, 0.9),
        ]
    )
    assert winner is None


@pytest.mark.asyncio
async def test_collab_orchestrator_local_capability_skips_federation() -> None:
    local = _LocalOrchestrator()

    class _NoopBroker:
        def __init__(self) -> None:
            self.advertise_called = False

        async def advertise(self, task: FederatedTask, peers: list[Peer]) -> list[BidResponse]:
            del task, peers
            self.advertise_called = True
            return []

        def select_peer(self, bids: list[BidResponse]) -> BidResponse | None:
            del bids
            return None

    broker = _NoopBroker()
    collab = CollabOrchestrator(
        local,
        broker=broker,  # type: ignore[arg-type]
        peers=[_peer("peer-a")],
        local_capabilities=["analysis", "reasoning"],
    )
    result = await collab.solve("Analyze this", ["analysis"])

    assert result["federated"] is False
    assert local.calls
    assert broker.advertise_called is False


@pytest.mark.asyncio
async def test_collab_orchestrator_delegates_and_merges_peer_attribution() -> None:
    local = _LocalOrchestrator()

    class _StubBroker:
        def __init__(self) -> None:
            self.advertise_called = False
            self.delegate_called = False

        async def advertise(self, task: FederatedTask, peers: list[Peer]) -> list[BidResponse]:
            del task, peers
            self.advertise_called = True
            return [BidResponse("peer-a", True, 0.2, 3.0, 0.8)]

        def select_peer(self, bids: list[BidResponse]) -> BidResponse | None:
            return bids[0] if bids else None

        async def delegate(self, task: FederatedTask, peer: Peer) -> FederatedResult:
            del task
            self.delegate_called = True
            return FederatedResult(
                task_id="delegated-task",
                peer_id=peer.peer_id,
                result="remote-result",
                cost_usd=0.2,
                time_s=1.5,
                success=True,
            )

    broker = _StubBroker()
    collab = CollabOrchestrator(
        local,
        broker=broker,  # type: ignore[arg-type]
        peers=[_peer("peer-a")],
        local_capabilities=["analysis"],
    )
    result = await collab.solve("Need translation", ["translation"])

    assert result["federated"] is True
    assert result["peer_id"] == "peer-a"
    assert broker.advertise_called is True
    assert broker.delegate_called is True
    assert local.memory_store.merged
    merged = local.memory_store.merged[0]
    assert merged["context"]["source_peer_id"] == "peer-a"


def test_federation_bid_endpoint_shape() -> None:
    payload = {
        "task_id": "task-api-bid",
        "description": "Need debate",
        "required_capabilities": ["debate"],
        "requester_instance_id": "remote-1",
        "deadline_s": 30,
        "context": {},
    }

    async def _run():
        async with lifespan(app):
            return await request(
                app,
                "POST",
                "/federation/tasks/bid",
                json_body=payload,
                headers=_auth_headers(),
            )

    response = asyncio.run(_run())
    assert response.status_code == 200
    body = response.json()
    assert {
        "peer_id",
        "can_fulfill",
        "estimated_cost_usd",
        "estimated_time_s",
        "confidence",
    } <= set(body.keys())


def test_federation_execute_endpoint_streams_tokens_and_result() -> None:
    payload = {
        "task_id": "task-api-exec",
        "description": "Provide a short answer",
        "required_capabilities": ["debate"],
        "requester_instance_id": "remote-1",
        "deadline_s": 30,
        "context": {},
    }

    async def _run():
        async with lifespan(app):
            orchestrator = app.state.orchestrator

            async def _stub_execute(**kwargs: Any) -> OrchestrationResult:  # noqa: ANN401
                return OrchestrationResult(
                    task_id="task-stub",
                    goal=str(kwargs.get("goal", "")),
                    mode=str(kwargs.get("mode", "debate")),  # type: ignore[arg-type]
                    final_answer="stubbed result",
                    confidence=90,
                    budget={"spent_usd": 0.0, "limit_usd": 0.0, "cost_by_provider_model": {}},
                    debate=None,
                    growth=None,
                )

            original_execute = orchestrator.execute
            orchestrator.execute = _stub_execute  # type: ignore[assignment]
            try:
                return await request(
                    app,
                    "POST",
                    "/federation/tasks/execute",
                    json_body=payload,
                    headers=_auth_headers(),
                )
            finally:
                orchestrator.execute = original_execute  # type: ignore[assignment]

    response = asyncio.run(_run())
    assert response.status_code == 200
    lines = [line for line in response.text.splitlines() if line.strip()]
    parsed = [json.loads(line) for line in lines]
    assert any(item.get("type") == "token" for item in parsed)
    assert any(item.get("type") == "result" for item in parsed)
