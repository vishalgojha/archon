"""Runtime event broker for Studio workflow executions."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from archon.evolution.engine import WorkflowDefinition


def _run_id() -> str:
    return f"studio-run-{uuid.uuid4().hex[:12]}"


@dataclass(slots=True, frozen=True)
class WorkflowRun:
    """One in-memory workflow run handle.

    Example:
        >>> WorkflowRun("run-1", "wf-1", "tenant-a").run_id
        'run-1'
    """

    run_id: str
    workflow_id: str
    tenant_id: str


class WorkflowRunBroker:
    """Broker workflow run events to Studio websocket subscribers.

    Example:
        >>> broker = WorkflowRunBroker()
        >>> broker.create_run("tenant-a", "wf-1").workflow_id
        'wf-1'
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}

    def create_run(self, tenant_id: str, workflow_id: str) -> WorkflowRun:
        """Create one run handle and event queue.

        Example:
            >>> broker = WorkflowRunBroker()
            >>> broker.create_run("tenant-a", "wf-1").tenant_id
            'tenant-a'
        """

        run = WorkflowRun(run_id=_run_id(), workflow_id=str(workflow_id), tenant_id=str(tenant_id))
        self._queues[run.run_id] = asyncio.Queue()
        return run

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        """Publish one event to the run queue.

        Example:
            >>> broker = WorkflowRunBroker()
            >>> run = broker.create_run("tenant-a", "wf-1")
            >>> __import__("asyncio").run(broker.publish(run.run_id, {"type":"x"})) is None
            True
        """

        queue = self._queues.get(str(run_id))
        if queue is not None:
            await queue.put(dict(event))

    async def subscribe(self, run_id: str):
        """Yield events from one run queue until a terminal event arrives.

        Example:
            >>> broker = WorkflowRunBroker()
            >>> hasattr(broker, "subscribe")
            True
        """

        queue = self._queues.get(str(run_id))
        if queue is None:
            raise KeyError(f"Unknown run_id '{run_id}'.")
        while True:
            event = await queue.get()
            yield event
            if str(event.get("type") or "").endswith("_completed") or event.get("terminal"):
                break


async def execute_workflow_run(
    *,
    broker: WorkflowRunBroker,
    run_id: str,
    workflow: WorkflowDefinition,
    orchestrator: Any,
) -> None:
    """Execute one workflow and publish lifecycle events.

    Example:
        >>> hasattr(execute_workflow_run, "__call__")
        True
    """

    await broker.publish(
        run_id,
        {"type": "workflow_started", "workflow_id": workflow.workflow_id, "run_id": run_id},
    )
    for step in workflow.steps:
        await broker.publish(
            run_id,
            {
                "type": "step_started",
                "run_id": run_id,
                "workflow_id": workflow.workflow_id,
                "step_id": step.step_id,
                "agent": step.agent,
                "action": step.action,
            },
        )
        await broker.publish(
            run_id,
            {
                "type": "step_completed",
                "run_id": run_id,
                "workflow_id": workflow.workflow_id,
                "step_id": step.step_id,
                "agent": step.agent,
            },
        )

    result = await orchestrator.execute(
        goal=str(workflow.metadata.get("goal") or workflow.name),
        mode="debate",
        context={"workflow_id": workflow.workflow_id, "workflow_name": workflow.name},
    )
    await broker.publish(
        run_id,
        {
            "type": "workflow_completed",
            "terminal": True,
            "run_id": run_id,
            "workflow_id": workflow.workflow_id,
            "final_answer": result.final_answer,
            "confidence": result.confidence,
        },
    )
