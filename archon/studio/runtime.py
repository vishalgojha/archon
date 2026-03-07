"""Runtime event broker for Studio workflow executions."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from archon.evolution.engine import WorkflowDefinition
from archon.studio.execution import StepExecutionResult, build_step_executor, build_synthesis_goal


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
            event_type = str(event.get("type") or "")
            if event.get("terminal") or event_type in {"workflow_completed", "workflow_failed"}:
                break


async def execute_workflow_run(
    *,
    broker: WorkflowRunBroker,
    run_id: str,
    workflow: WorkflowDefinition,
    orchestrator: Any,
    tenant_id: str,
) -> None:
    """Execute one workflow and publish lifecycle events.

    Example:
        >>> hasattr(execute_workflow_run, "__call__")
        True
    """
    step_results: list[StepExecutionResult] = []
    execution_layer = "initializing"

    async def sink(event: dict[str, Any]) -> None:
        await broker.publish(run_id, dict(event))

    try:
        executor = build_step_executor()
        execution_layer = executor.backend_name
        await broker.publish(
            run_id,
            {
                "type": "workflow_started",
                "workflow_id": workflow.workflow_id,
                "workflow_name": workflow.name,
                "run_id": run_id,
                "tenant_id": tenant_id,
                "execution_layer": execution_layer,
            },
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
                    "execution_layer": execution_layer,
                },
            )
            step_result = await executor.execute_step(
                step=step,
                workflow=workflow,
                run_id=run_id,
                tenant_id=tenant_id,
                prior_results=list(step_results),
                orchestrator=orchestrator,
                event_sink=sink,
            )
            step_results.append(step_result)
            await broker.publish(
                run_id,
                {
                    "type": "step_completed",
                    "run_id": run_id,
                    "workflow_id": workflow.workflow_id,
                    "step_id": step.step_id,
                    "agent": step.agent,
                    "action": step.action,
                    **step_result.to_event_payload(),
                },
            )

        result = await orchestrator.execute(
            goal=build_synthesis_goal(workflow, step_results),
            mode="debate",
            context={
                "workflow_id": workflow.workflow_id,
                "workflow_name": workflow.name,
                "execution_layer": executor.backend_name,
                "tenant_id": tenant_id,
                "step_results": [
                    {
                        "step_id": row.step_id,
                        "executor": row.executor,
                        "status": row.status,
                        "summary": row.summary,
                        "output_text": row.output_text,
                        "metadata": dict(row.metadata),
                    }
                    for row in step_results
                ],
            },
            event_sink=sink,
        )
        await broker.publish(
            run_id,
            {
                "type": "workflow_completed",
                "terminal": True,
                "run_id": run_id,
                "workflow_id": workflow.workflow_id,
                "execution_layer": execution_layer,
                "final_answer": result.final_answer,
                "confidence": result.confidence,
            },
        )
    except Exception as exc:
        await broker.publish(
            run_id,
            {
                "type": "workflow_failed",
                "terminal": True,
                "run_id": run_id,
                "workflow_id": workflow.workflow_id,
                "execution_layer": execution_layer,
                "message": str(exc),
            },
        )
