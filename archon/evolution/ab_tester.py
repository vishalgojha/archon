"""A/B testing utilities for workflow evolution experiments."""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from archon.evolution.engine import WorkflowDefinition

WorkflowExecutor = Callable[[WorkflowDefinition, "SyntheticTask"], Awaitable[dict[str, Any]]]
CorrectnessJudge = Callable[["SyntheticTask", Any], Awaitable[float] | float]


@dataclass(slots=True, frozen=True)
class SyntheticTask:
    """Synthetic evaluation task used for workflow A/B trials."""

    task_id: str
    description: str
    expected_output_schema: dict[str, Any]
    difficulty: str


@dataclass(slots=True)
class TaskTrialResult:
    """Per-task outcome for one workflow variant."""

    task_id: str
    correctness: float
    latency_ms: float
    cost_usd: float
    composite_score: float
    output: Any = None
    error: str | None = None


@dataclass(slots=True)
class TrialResult:
    """A/B trial summary with per-task and aggregate scores."""

    workflow_a_id: str
    workflow_b_id: str
    workflow_a_results: list[TaskTrialResult] = field(default_factory=list)
    workflow_b_results: list[TaskTrialResult] = field(default_factory=list)
    aggregate_scores: dict[str, float] = field(default_factory=dict)
    recommended_winner: str | None = None


class ABTester:
    """Runs workflow A/B trials on synthetic tasks."""

    def __init__(
        self,
        *,
        executor: WorkflowExecutor | None = None,
        correctness_judge: CorrectnessJudge | None = None,
    ) -> None:
        self._executor = executor
        self._judge = correctness_judge

    async def run_trial(
        self,
        workflow_a: WorkflowDefinition,
        workflow_b: WorkflowDefinition,
        tasks: list[SyntheticTask],
    ) -> TrialResult:
        """Run workflows on synthetic tasks and return scoring summary."""

        workflow_a_results = await self._run_workflow(workflow_a, tasks)
        workflow_b_results = await self._run_workflow(workflow_b, tasks)

        all_results = workflow_a_results + workflow_b_results
        max_latency = max((result.latency_ms for result in all_results), default=0.0)
        max_cost = max((result.cost_usd for result in all_results), default=0.0)
        for result in all_results:
            result.composite_score = self.calculate_composite_score(
                correctness=result.correctness,
                latency_ms=result.latency_ms,
                cost_usd=result.cost_usd,
                max_latency_ms=max_latency,
                max_cost_usd=max_cost,
            )

        aggregate_scores = {
            workflow_a.workflow_id: _average([row.composite_score for row in workflow_a_results]),
            workflow_b.workflow_id: _average([row.composite_score for row in workflow_b_results]),
        }
        winner: str | None = None
        if aggregate_scores[workflow_a.workflow_id] > aggregate_scores[workflow_b.workflow_id]:
            winner = workflow_a.workflow_id
        elif aggregate_scores[workflow_b.workflow_id] > aggregate_scores[workflow_a.workflow_id]:
            winner = workflow_b.workflow_id

        return TrialResult(
            workflow_a_id=workflow_a.workflow_id,
            workflow_b_id=workflow_b.workflow_id,
            workflow_a_results=workflow_a_results,
            workflow_b_results=workflow_b_results,
            aggregate_scores=aggregate_scores,
            recommended_winner=winner,
        )

    async def _run_workflow(
        self, workflow: WorkflowDefinition, tasks: list[SyntheticTask]
    ) -> list[TaskTrialResult]:
        async_tasks = [asyncio.create_task(self._run_task(workflow, task)) for task in tasks]
        if not async_tasks:
            return []
        return await asyncio.gather(*async_tasks)

    async def _run_task(self, workflow: WorkflowDefinition, task: SyntheticTask) -> TaskTrialResult:
        start = time.perf_counter()
        try:
            execution = await self._execute(workflow, task)
            output = execution.get("output")
            latency_ms = float(execution.get("latency_ms", (time.perf_counter() - start) * 1000))
            cost_usd = float(execution.get("cost_usd", 0.0))
            correctness = await self._judge_correctness(task, output)
            return TaskTrialResult(
                task_id=task.task_id,
                correctness=correctness,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                composite_score=0.0,
                output=output,
            )
        except Exception as exc:
            latency_ms = float((time.perf_counter() - start) * 1000)
            return TaskTrialResult(
                task_id=task.task_id,
                correctness=0.0,
                latency_ms=latency_ms,
                cost_usd=0.0,
                composite_score=0.0,
                output=None,
                error=str(exc),
            )

    async def _execute(self, workflow: WorkflowDefinition, task: SyntheticTask) -> dict[str, Any]:
        if self._executor is None:
            raise RuntimeError("ABTester requires an executor; none was provided.")
        return await self._executor(workflow, task)

    async def _judge_correctness(self, task: SyntheticTask, output: Any) -> float:
        if self._judge is not None:
            judged = self._judge(task, output)
            if inspect.isawaitable(judged):
                judged = await judged
            return _clamp(float(judged))

        schema_keys = set(task.expected_output_schema.keys())
        if not schema_keys:
            return 1.0 if output is not None else 0.0
        if not isinstance(output, dict):
            return 0.0
        matched = sum(1 for key in schema_keys if key in output and output[key] is not None)
        return _clamp(matched / max(1, len(schema_keys)))

    @staticmethod
    def calculate_composite_score(
        *,
        correctness: float,
        latency_ms: float,
        cost_usd: float,
        max_latency_ms: float,
        max_cost_usd: float,
    ) -> float:
        """Composite score formula used by trial ranking."""

        normalized_latency = (latency_ms / max_latency_ms) if max_latency_ms > 0 else 0.0
        normalized_cost = (cost_usd / max_cost_usd) if max_cost_usd > 0 else 0.0
        score = (
            0.6 * _clamp(correctness)
            + 0.2 * (1.0 - _clamp(normalized_latency))
            + 0.2 * (1.0 - _clamp(normalized_cost))
        )
        return round(score, 6)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
