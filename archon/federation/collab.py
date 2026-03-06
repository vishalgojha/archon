"""Cross-instance federation collaboration primitives for co-solving tasks."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from archon.core.approval_gate import ApprovalGate, EventSink
from archon.federation.peer_discovery import Peer


@dataclass(slots=True, frozen=True)
class FederatedTask:
    """Task advertisement payload for remote federation peers."""

    task_id: str
    description: str
    required_capabilities: list[str]
    requester_instance_id: str
    deadline_s: float
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class BidResponse:
    """Bid response from one remote federation peer."""

    peer_id: str
    can_fulfill: bool
    estimated_cost_usd: float
    estimated_time_s: float
    confidence: float


@dataclass(slots=True, frozen=True)
class FederatedResult:
    """Delegated execution result from a remote peer."""

    task_id: str
    peer_id: str
    result: str
    cost_usd: float
    time_s: float
    success: bool


class TaskBroker:
    """Advertises federation tasks, selects peers, and delegates execution."""

    def __init__(
        self,
        *,
        approval_gate: ApprovalGate | None = None,
        event_sink: EventSink | None = None,
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.approval_gate = approval_gate or ApprovalGate(auto_approve_in_test=True)
        self.event_sink = event_sink
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def advertise(self, task: FederatedTask, peers: list[Peer]) -> list[BidResponse]:
        """Broadcast task to all peers and collect bid responses."""

        jobs = [asyncio.create_task(self._request_bid(task, peer)) for peer in peers]
        if not jobs:
            return []
        rows = await asyncio.gather(*jobs)
        return [row for row in rows if row is not None]

    def select_peer(self, bids: list[BidResponse]) -> BidResponse | None:
        """Choose best feasible peer using cost*time/confidence score."""

        viable = [row for row in bids if row.can_fulfill]
        if not viable:
            return None

        def score(row: BidResponse) -> float:
            confidence = max(row.confidence, 0.001)
            return (
                max(row.estimated_cost_usd, 0.0) * max(row.estimated_time_s, 0.001)
            ) / confidence

        return min(viable, key=score)

    async def delegate(self, task: FederatedTask, peer: Peer) -> FederatedResult:
        """Delegate task execution to selected peer and return remote result."""

        await self._gate_external_call(
            {
                "kind": "federation_delegate",
                "peer_id": peer.peer_id,
                "address": peer.address,
                "task_id": task.task_id,
            }
        )

        started = time.monotonic()
        payload = asdict(task)
        try:
            response = await self._client.post(
                f"{peer.address.rstrip('/')}/federation/tasks/execute",
                json=payload,
                timeout=max(1.0, task.deadline_s),
            )
        except Exception:
            elapsed = max(0.0, time.monotonic() - started)
            return FederatedResult(
                task_id=task.task_id,
                peer_id=peer.peer_id,
                result="",
                cost_usd=0.0,
                time_s=elapsed,
                success=False,
            )

        elapsed = max(0.0, time.monotonic() - started)
        parsed = _parse_delegate_response(response)
        return FederatedResult(
            task_id=task.task_id,
            peer_id=peer.peer_id,
            result=parsed["result"],
            cost_usd=float(parsed["cost_usd"]),
            time_s=float(parsed["time_s"] if parsed["time_s"] > 0 else elapsed),
            success=bool(parsed["success"]) and int(response.status_code) < 400,
        )

    async def _request_bid(self, task: FederatedTask, peer: Peer) -> BidResponse | None:
        await self._gate_external_call(
            {
                "kind": "federation_bid",
                "peer_id": peer.peer_id,
                "address": peer.address,
                "task_id": task.task_id,
            }
        )

        try:
            response = await self._client.post(
                f"{peer.address.rstrip('/')}/federation/tasks/bid",
                json=asdict(task),
                timeout=max(1.0, task.deadline_s),
            )
            if int(response.status_code) >= 400:
                return BidResponse(
                    peer_id=peer.peer_id,
                    can_fulfill=False,
                    estimated_cost_usd=0.0,
                    estimated_time_s=0.0,
                    confidence=0.0,
                )
            payload = response.json()
            return BidResponse(
                peer_id=str(payload.get("peer_id") or peer.peer_id),
                can_fulfill=bool(payload.get("can_fulfill", False)),
                estimated_cost_usd=float(payload.get("estimated_cost_usd", 0.0) or 0.0),
                estimated_time_s=float(payload.get("estimated_time_s", 0.0) or 0.0),
                confidence=float(payload.get("confidence", 0.0) or 0.0),
            )
        except Exception:
            return BidResponse(
                peer_id=peer.peer_id,
                can_fulfill=False,
                estimated_cost_usd=0.0,
                estimated_time_s=0.0,
                confidence=0.0,
            )

    async def _gate_external_call(self, context: dict[str, Any]) -> None:
        action_id = f"fed-{uuid.uuid4().hex[:12]}"
        gate_context = dict(context)
        if self.event_sink is not None:
            gate_context["event_sink"] = self.event_sink
        await self.approval_gate.check(
            action="external_api_call",
            context=gate_context,
            action_id=action_id,
        )


class CollabOrchestrator:
    """Wraps local orchestrator with peer advertisement and delegated execution."""

    def __init__(
        self,
        orchestrator,
        *,
        broker: TaskBroker | None = None,
        peers: list[Peer] | None = None,
        local_capabilities: list[str] | None = None,
        instance_id: str = "local-instance",
    ) -> None:
        self.orchestrator = orchestrator
        self.broker = broker or TaskBroker()
        self.peers = list(peers or [])
        self.instance_id = str(instance_id)
        self.local_capabilities = set(
            item.strip().lower()
            for item in (
                local_capabilities or ["debate", "growth", "analysis", "reasoning", "translation"]
            )
            if str(item).strip()
        )

    def capability_gap(self, task: FederatedTask) -> list[str]:
        """Return missing capabilities that local instance cannot satisfy."""

        required = [
            str(item).strip().lower() for item in task.required_capabilities if str(item).strip()
        ]
        return [item for item in required if item not in self.local_capabilities]

    async def solve(
        self, task_description: str, required_capabilities: list[str]
    ) -> dict[str, Any]:
        """Solve locally when possible, otherwise delegate to best federation peer."""

        task = FederatedTask(
            task_id=f"fedt-{uuid.uuid4().hex[:12]}",
            description=str(task_description),
            required_capabilities=[str(item) for item in required_capabilities],
            requester_instance_id=self.instance_id,
            deadline_s=30.0,
            context={},
        )
        gap = self.capability_gap(task)

        if not gap:
            local = await self.orchestrator.execute(
                goal=task.description,
                mode="debate",
                context={"federation": "local"},
            )
            return {
                "task_id": task.task_id,
                "peer_id": None,
                "result": local.final_answer,
                "success": True,
                "federated": False,
            }

        bids = await self.broker.advertise(task, self.peers)
        winner = self.broker.select_peer(bids)
        if winner is None:
            local = await self.orchestrator.execute(
                goal=task.description,
                mode="debate",
                context={"federation": "fallback", "capability_gap": gap},
            )
            return {
                "task_id": task.task_id,
                "peer_id": None,
                "result": local.final_answer,
                "success": True,
                "federated": False,
            }

        peer = next((row for row in self.peers if row.peer_id == winner.peer_id), None)
        if peer is None:
            return {
                "task_id": task.task_id,
                "peer_id": winner.peer_id,
                "result": "",
                "success": False,
                "federated": True,
            }

        delegated = await self.broker.delegate(task, peer)
        if delegated.success:
            await self._merge_into_memory(task, delegated)

        return {
            "task_id": delegated.task_id,
            "peer_id": delegated.peer_id,
            "result": delegated.result,
            "success": delegated.success,
            "federated": True,
            "cost_usd": delegated.cost_usd,
            "time_s": delegated.time_s,
        }

    async def _merge_into_memory(self, task: FederatedTask, delegated: FederatedResult) -> None:
        memory_store = getattr(self.orchestrator, "memory_store", None)
        if memory_store is None:
            return

        add_entry = getattr(memory_store, "add_entry", None)
        if not callable(add_entry):
            return

        await add_entry(
            task=task.description,
            context={
                "source": "federation_delegate",
                "source_peer_id": delegated.peer_id,
                "task_id": delegated.task_id,
            },
            actions_taken=["federation_delegate"],
            causal_reasoning="Remote peer fulfilled missing capabilities.",
            actual_outcome=delegated.result,
            delta="Delegated federation result merged into local memory.",
            reuse_conditions="Use when similar capability gap appears.",
        )


def _parse_delegate_response(response: httpx.Response) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "result": "",
        "cost_usd": 0.0,
        "time_s": 0.0,
        "success": int(response.status_code) < 400,
    }

    try:
        data = response.json()
    except Exception:
        data = None

    if isinstance(data, dict):
        payload["result"] = str(data.get("result") or data.get("output") or "")
        payload["cost_usd"] = float(data.get("cost_usd", 0.0) or 0.0)
        payload["time_s"] = float(data.get("time_s", 0.0) or 0.0)
        if "success" in data:
            payload["success"] = bool(data.get("success"))
        return payload

    tokens: list[str] = []
    text = str(getattr(response, "text", "") or "")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        row_type = str(row.get("type", ""))
        if row_type == "token":
            tokens.append(str(row.get("content", "")))
        if row_type == "result":
            payload["result"] = str(row.get("result", "")) or "".join(tokens)
            payload["cost_usd"] = float(row.get("cost_usd", 0.0) or 0.0)
            payload["time_s"] = float(row.get("time_s", 0.0) or 0.0)
            payload["success"] = bool(row.get("success", True))

    if not payload["result"]:
        payload["result"] = "".join(tokens)
    return payload
