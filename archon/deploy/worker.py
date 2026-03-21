"""SQLite-backed deployment worker used by on-prem compose and Helm assets."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from archon.config import ArchonConfig, load_archon_config
from archon.core.memory_store import MemoryStore
from archon.core.orchestrator import OrchestrationResult, Orchestrator, TaskMode
from archon.observability.metrics import Metrics
from archon.observability.tracing import TracingSetup

TaskStatus = Literal["pending", "running", "completed", "failed"]


@dataclass(slots=True)
class QueuedTask:
    """One persisted worker queue record.

    Example:
        >>> QueuedTask(task_id="task-1", goal="Draft plan", mode="debate", language=None, context={}, status="pending", attempts=0, created_at=0.0).status
        'pending'
    """

    task_id: str
    goal: str
    mode: TaskMode
    language: str | None
    context: dict[str, Any]
    status: TaskStatus
    attempts: int
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class WorkerQueue:
    """SQLite-backed task queue for the deployment worker.

    Example:
        >>> queue = WorkerQueue(":memory:")
        >>> queue.enqueue(goal="Draft a rollout plan").status
        'pending'
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def enqueue(
        self,
        *,
        goal: str,
        mode: TaskMode = "debate",
        language: str | None = None,
        context: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> QueuedTask:
        """Insert one task into the pending queue.

        Example:
            >>> queue = WorkerQueue(":memory:")
            >>> row = queue.enqueue(goal="Explain CAP theorem")
            >>> row.task_id.startswith("task-")
            True
        """

        record = QueuedTask(
            task_id=str(task_id or f"task-{uuid.uuid4().hex[:12]}"),
            goal=str(goal),
            mode=mode,
            language=language,
            context=dict(context or {}),
            status="pending",
            attempts=0,
            created_at=time.time(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO worker_tasks (
                    task_id,
                    goal,
                    mode,
                    language,
                    context_json,
                    status,
                    attempts,
                    created_at,
                    started_at,
                    finished_at,
                    result_json,
                    error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.task_id,
                    record.goal,
                    record.mode,
                    record.language,
                    _json_dumps(record.context),
                    record.status,
                    record.attempts,
                    record.created_at,
                    None,
                    None,
                    None,
                    None,
                ),
            )
        return record

    def claim_next(self) -> QueuedTask | None:
        """Lease the next pending task for processing.

        Example:
            >>> queue = WorkerQueue(":memory:")
            >>> _ = queue.enqueue(goal="Review roadmap")
            >>> queue.claim_next() is not None
            True
        """

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT *
                FROM worker_tasks
                WHERE status = 'pending'
                ORDER BY created_at ASC, task_id ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            started_at = time.time()
            conn.execute(
                """
                UPDATE worker_tasks
                SET status = 'running',
                    started_at = ?,
                    attempts = attempts + 1
                WHERE task_id = ?
                """,
                (started_at, row["task_id"]),
            )
            conn.commit()
        return self.get(str(row["task_id"]))

    def complete(self, task_id: str, payload: dict[str, Any]) -> QueuedTask | None:
        """Mark one running task as completed.

        Example:
            >>> queue = WorkerQueue(":memory:")
            >>> task = queue.enqueue(goal="Hello")
            >>> _ = queue.claim_next()
            >>> queue.complete(task.task_id, {"ok": True}).status
            'completed'
        """

        return self._finish(task_id, status="completed", payload=payload, error=None)

    def fail(self, task_id: str, error: str) -> QueuedTask | None:
        """Mark one running task as failed.

        Example:
            >>> queue = WorkerQueue(":memory:")
            >>> task = queue.enqueue(goal="Hello")
            >>> _ = queue.claim_next()
            >>> queue.fail(task.task_id, "boom").status
            'failed'
        """

        return self._finish(task_id, status="failed", payload=None, error=error)

    def get(self, task_id: str) -> QueuedTask | None:
        """Fetch one queued task by id.

        Example:
            >>> queue = WorkerQueue(":memory:")
            >>> task = queue.enqueue(goal="Hello")
            >>> queue.get(task.task_id).task_id == task.task_id
            True
        """

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM worker_tasks WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
        return _row_to_task(row)

    def list_pending(self) -> list[QueuedTask]:
        """List currently pending tasks.

        Example:
            >>> queue = WorkerQueue(":memory:")
            >>> _ = queue.enqueue(goal="Hello")
            >>> len(queue.list_pending())
            1
        """

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM worker_tasks
                WHERE status = 'pending'
                ORDER BY created_at ASC, task_id ASC
                """
            ).fetchall()
        return [_row_to_task(row) for row in rows if row is not None]

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_tasks (
                    task_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    language TEXT,
                    context_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    result_json TEXT,
                    error TEXT
                )
                """
            )

    def _finish(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        payload: dict[str, Any] | None,
        error: str | None,
    ) -> QueuedTask | None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE worker_tasks
                SET status = ?,
                    finished_at = ?,
                    result_json = ?,
                    error = ?
                WHERE task_id = ?
                """,
                (
                    status,
                    time.time(),
                    _json_dumps(payload) if payload is not None else None,
                    str(error) if error else None,
                    str(task_id),
                ),
            )
        return self.get(task_id)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


class DeploymentWorker:
    """Background worker that executes queued ARCHON tasks through the orchestrator.

    Example:
        >>> worker = DeploymentWorker(queue=WorkerQueue(":memory:"), config=ArchonConfig())
        >>> isinstance(worker.metrics, Metrics)
        True
    """

    def __init__(
        self,
        *,
        queue: WorkerQueue,
        config: ArchonConfig,
        memory_db_path: str | Path | None = None,
        orchestrator: Orchestrator | None = None,
    ) -> None:
        self.queue = queue
        self.metrics = Metrics.get_instance()
        self.tracer = TracingSetup.configure(
            service_name=os.getenv("ARCHON_SERVICE_NAME", "archon-worker"),
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
        )
        self.orchestrator = orchestrator or Orchestrator(
            config=config,
        )
        self.orchestrator.memory_store = MemoryStore(
            db_path=str(memory_db_path or (_runtime_dir() / "archon_memory.sqlite3"))
        )
        TracingSetup.instrument_orchestrator(self.orchestrator)

    async def process_next(self) -> QueuedTask | None:
        """Process one queued task if available.

        Example:
            >>> worker = DeploymentWorker(queue=WorkerQueue(":memory:"), config=ArchonConfig())
            >>> __import__("asyncio").run(worker.process_next()) is None
            True
        """

        claimed = await asyncio.to_thread(self.queue.claim_next)
        if claimed is None:
            return None
        started = time.perf_counter()
        with self.tracer.start_as_current_span("worker.process_task") as span:
            span.set_attributes(
                {
                    "task_id": claimed.task_id,
                    "mode": claimed.mode,
                    "attempts": claimed.attempts,
                }
            )
            events: list[dict[str, Any]] = []

            async def capture_event(event: dict[str, Any]) -> None:
                events.append(dict(event))

            try:
                result = await self.orchestrator.execute(
                    goal=claimed.goal,
                    mode=claimed.mode,
                    task_id=claimed.task_id,
                    language=claimed.language,
                    context=dict(claimed.context),
                    event_sink=capture_event,
                )
            except Exception as exc:
                duration = time.perf_counter() - started
                span.set_attribute("status", "failed")
                span.record_exception(exc)
                self.metrics.record_worker_task(
                    mode=claimed.mode,
                    status="failed",
                    duration_seconds=duration,
                )
                return await asyncio.to_thread(self.queue.fail, claimed.task_id, str(exc))

            duration = time.perf_counter() - started
            payload = _serialize_result(result, events)
            span.set_attributes(
                {
                    "status": "completed",
                    "confidence": result.confidence,
                    "event_count": len(events),
                }
            )
            self.metrics.record_worker_task(
                mode=claimed.mode,
                status="completed",
                duration_seconds=duration,
            )
            return await asyncio.to_thread(self.queue.complete, claimed.task_id, payload)

    async def run(self, *, poll_interval_seconds: float = 15.0, once: bool = False) -> None:
        """Run the worker loop until stopped.

        Example:
            >>> worker = DeploymentWorker(queue=WorkerQueue(":memory:"), config=ArchonConfig())
            >>> __import__("asyncio").run(worker.run(poll_interval_seconds=0.0, once=True)) is None
            True
        """

        idle_sleep = max(0.25, float(poll_interval_seconds))
        while True:
            processed = await self.process_next()
            if once:
                return
            if processed is None:
                await asyncio.sleep(idle_sleep)

    async def aclose(self) -> None:
        """Close shared worker resources.

        Example:
            >>> worker = DeploymentWorker(queue=WorkerQueue(":memory:"), config=ArchonConfig())
            >>> __import__("asyncio").run(worker.aclose()) is None
            True
        """

        await self.orchestrator.aclose()


async def run_worker_async(
    *,
    poll_interval_seconds: float = 15.0,
    once: bool = False,
    config_path: str | Path | None = None,
    queue_path: str | Path | None = None,
) -> None:
    """Run the ARCHON deployment worker.

    Example:
        >>> __import__("asyncio").run(run_worker_async(once=True)) is None
        True
    """

    queue = WorkerQueue(queue_path or _worker_db_path())
    worker = DeploymentWorker(
        queue=queue,
        config=load_archon_config(config_path or os.getenv("ARCHON_CONFIG", "config.archon.yaml")),
        memory_db_path=_memory_db_path(),
    )
    try:
        await worker.run(poll_interval_seconds=poll_interval_seconds, once=once)
    finally:
        await worker.aclose()


def run_worker(
    *,
    poll_interval_seconds: float = 15.0,
    once: bool = False,
    config_path: str | Path | None = None,
    queue_path: str | Path | None = None,
) -> None:
    """Synchronous wrapper for the async worker loop.

    Example:
        >>> run_worker(poll_interval_seconds=0.0, once=True) is None
        True
    """

    asyncio.run(
        run_worker_async(
            poll_interval_seconds=poll_interval_seconds,
            once=once,
            config_path=config_path,
            queue_path=queue_path,
        )
    )


def _runtime_dir() -> Path:
    configured = str(os.getenv("ARCHON_RUNTIME_DIR", "")).strip()
    if configured:
        root = Path(configured)
    elif os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA", tempfile.gettempdir())) / "ARCHON"
    else:
        root = Path.home() / ".archon"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _worker_db_path() -> Path:
    configured = str(os.getenv("ARCHON_WORKER_DB_PATH", "")).strip()
    if configured:
        return Path(configured)
    return _runtime_dir() / "archon_worker.sqlite3"


def _memory_db_path() -> Path:
    configured = (
        str(os.getenv("ARCHON_MEMORY_DB", "")).strip()
        or str(os.getenv("ARCHON_MEMORY_DB_PATH", "")).strip()
    )
    if configured:
        return Path(configured)
    return _runtime_dir() / "archon_memory.sqlite3"


def _serialize_result(
    result: OrchestrationResult,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "result": asdict(result),
        "events": [dict(event) for event in events],
    }


def _json_dumps(payload: dict[str, Any] | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=True, sort_keys=True)


def _row_to_task(row: sqlite3.Row | None) -> QueuedTask | None:
    if row is None:
        return None
    result_json = row["result_json"]
    return QueuedTask(
        task_id=str(row["task_id"]),
        goal=str(row["goal"]),
        mode=str(row["mode"]),
        language=str(row["language"]) if row["language"] is not None else None,
        context=json.loads(str(row["context_json"]) or "{}"),
        status=str(row["status"]),
        attempts=int(row["attempts"]),
        created_at=float(row["created_at"]),
        started_at=float(row["started_at"]) if row["started_at"] is not None else None,
        finished_at=float(row["finished_at"]) if row["finished_at"] is not None else None,
        result=json.loads(str(result_json)) if result_json else None,
        error=str(row["error"]) if row["error"] is not None else None,
    )


def main() -> None:
    """Console entrypoint for the deployment worker."""

    run_worker(
        poll_interval_seconds=float(os.getenv("ARCHON_WORKER_POLL_SECONDS", "15")),
        once=str(os.getenv("ARCHON_WORKER_ONCE", "")).strip().lower() == "true",
        config_path=os.getenv("ARCHON_CONFIG", "config.archon.yaml"),
        queue_path=os.getenv("ARCHON_WORKER_DB_PATH") or None,
    )


if __name__ == "__main__":
    main()
