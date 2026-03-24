"""Coverage for the deployment worker queue, runtime, and observability hooks."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from archon.config import ArchonConfig
from archon.deploy.worker import DeploymentWorker, WorkerQueue, run_worker_async
from archon.observability.metrics import Metrics
from archon.observability.tracing import TracingSetup


def test_worker_queue_claims_oldest_pending_task(tmp_path: Path) -> None:
    queue = WorkerQueue(tmp_path / "worker.sqlite3")
    first = queue.enqueue(goal="first task", mode="debate")
    second = queue.enqueue(goal="second task", mode="debate")

    claimed = queue.claim_next()
    pending = queue.list_pending()

    assert claimed is not None
    assert claimed.task_id == first.task_id
    assert [row.task_id for row in pending] == [second.task_id]


@pytest.mark.asyncio
async def test_worker_processes_queued_task_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARCHON_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "worker-openrouter-key")
    Metrics.reset_for_tests(force_noop=True)
    TracingSetup.reset_for_tests(force_noop=True)
    queue = WorkerQueue(tmp_path / "worker.sqlite3")
    queued = queue.enqueue(
        goal="Explain CAP theorem simply",
        mode="debate",
        context={"tenant_id": "tenant-worker"},
    )
    worker = DeploymentWorker(queue=queue, config=ArchonConfig())

    try:
        processed = await worker.process_next()
    finally:
        await worker.aclose()

    assert processed is not None
    assert processed.status == "completed"
    assert processed.result is not None
    assert processed.result["result"]["task_id"] == queued.task_id
    assert processed.result["result"]["mode"] == "debate"
    assert processed.result["events"][0]["type"] == "task_started"
    assert any(event["type"] == "task_completed" for event in processed.result["events"])
    assert (tmp_path / "archon_memory.sqlite3").exists()

    metrics_text = Metrics.get_instance().render_prometheus_text()
    assert 'archon_worker_tasks_total{mode="debate",status="completed"} 1.0' in metrics_text

    spans = TracingSetup.list_spans(limit=50)
    worker_span = next(span for span in spans if span["name"] == "worker.process_task")
    assert worker_span["attributes"]["task_id"] == queued.task_id
    assert worker_span["attributes"]["status"] == "completed"


@pytest.mark.asyncio
async def test_worker_marks_failures_without_crashing(tmp_path: Path) -> None:
    Metrics.reset_for_tests(force_noop=True)
    TracingSetup.reset_for_tests(force_noop=True)

    class _FailingOrchestrator:
        def __init__(self) -> None:
            self.memory_store = None

        async def execute(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            raise RuntimeError("boom")

        async def aclose(self) -> None:
            return None

    queue = WorkerQueue(tmp_path / "worker.sqlite3")
    queued = queue.enqueue(goal="will fail", mode="debate")
    worker = DeploymentWorker(
        queue=queue,
        config=ArchonConfig(),
        orchestrator=_FailingOrchestrator(),  # type: ignore[arg-type]
        memory_db_path=tmp_path / "archon_memory.sqlite3",
    )

    try:
        processed = await worker.process_next()
    finally:
        await worker.aclose()

    assert processed is not None
    assert processed.status == "failed"
    assert processed.error == "boom"
    stored = queue.get(queued.task_id)
    assert stored is not None
    assert stored.status == "failed"

    metrics_text = Metrics.get_instance().render_prometheus_text()
    assert 'archon_worker_tasks_total{mode="debate",status="failed"} 1.0' in metrics_text


def test_run_worker_async_once_exits_cleanly_without_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARCHON_RUNTIME_DIR", str(tmp_path))
    Metrics.reset_for_tests(force_noop=True)
    TracingSetup.reset_for_tests(force_noop=True)

    asyncio.run(
        run_worker_async(
            once=True,
            queue_path=tmp_path / "worker.sqlite3",
            config_path=tmp_path / "missing-config.archon.yaml",
        )
    )

    queue = WorkerQueue(tmp_path / "worker.sqlite3")
    assert queue.list_pending() == []
