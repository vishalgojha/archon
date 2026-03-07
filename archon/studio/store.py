"""SQLite workflow store for ARCHON Studio definitions."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from archon.compliance.encryption import EncryptionLayer
from archon.compliance.retention import RetentionRule
from archon.evolution.engine import Step, WorkflowDefinition

STUDIO_WORKFLOW_RETENTION_RULE = RetentionRule(
    entity_type="studio_workflow",
    retention_days=365,
    action="archive",
)


def _workflow_id() -> str:
    return f"studio_{uuid.uuid4().hex[:12]}"


def _default_master_key() -> bytes:
    env = str(os.getenv("ARCHON_MASTER_KEY", "")).strip()
    if env:
        try:
            return EncryptionLayer.master_key_from_env()
        except ValueError:
            pass
    return b"s" * 32


@dataclass(slots=True, frozen=True)
class StoredWorkflow:
    """One stored Studio workflow metadata row.

    Example:
        >>> StoredWorkflow("wf_1", "tenant-a", "Demo", 1.0).name
        'Demo'
    """

    workflow_id: str
    tenant_id: str
    name: str
    updated_at: float


class StudioWorkflowStore:
    """Persist Studio workflows in SQLite with encrypted definitions.

    Example:
        >>> store = StudioWorkflowStore(path=":memory:")
        >>> store.list("tenant-a")
        []
    """

    def __init__(
        self, path: str | Path = "archon_studio.sqlite3", *, master_key: bytes | None = None
    ) -> None:
        self.path = Path(path)
        self._master_key = master_key or _default_master_key()
        self._init_db()

    def save(
        self,
        tenant_id: str,
        workflow: WorkflowDefinition,
        *,
        workflow_id: str | None = None,
    ) -> StoredWorkflow:
        """Insert or update one workflow definition.

        Example:
            >>> store = StudioWorkflowStore(path=":memory:")
            >>> workflow = WorkflowDefinition("wf","Demo",[],{},1,1.0)
            >>> store.save("tenant-a", workflow).tenant_id
            'tenant-a'
        """

        now = time.time()
        wid = str(workflow_id or workflow.workflow_id or _workflow_id())
        payload = _workflow_to_json(workflow, workflow_id=wid)
        encrypted = self._encrypt(tenant_id, payload)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO studio_workflows(workflow_id, tenant_id, name, encrypted_definition_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    name=excluded.name,
                    encrypted_definition_json=excluded.encrypted_definition_json,
                    updated_at=excluded.updated_at
                """,
                (wid, str(tenant_id), workflow.name, encrypted, now, now),
            )
        return StoredWorkflow(
            workflow_id=wid, tenant_id=str(tenant_id), name=workflow.name, updated_at=now
        )

    def list(self, tenant_id: str) -> list[StoredWorkflow]:
        """List workflow metadata for one tenant.

        Example:
            >>> store = StudioWorkflowStore(path=":memory:")
            >>> store.list("tenant-a")
            []
        """

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT workflow_id, tenant_id, name, updated_at
                FROM studio_workflows
                WHERE tenant_id = ?
                ORDER BY updated_at DESC, workflow_id DESC
                """,
                (str(tenant_id),),
            ).fetchall()
        return [
            StoredWorkflow(
                workflow_id=str(row["workflow_id"]),
                tenant_id=str(row["tenant_id"]),
                name=str(row["name"]),
                updated_at=float(row["updated_at"]),
            )
            for row in rows
        ]

    def get(self, tenant_id: str, workflow_id: str) -> WorkflowDefinition | None:
        """Load one stored workflow definition.

        Example:
            >>> store = StudioWorkflowStore(path=":memory:")
            >>> store.get("tenant-a", "missing") is None
            True
        """

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT encrypted_definition_json
                FROM studio_workflows
                WHERE tenant_id = ? AND workflow_id = ?
                """,
                (str(tenant_id), str(workflow_id)),
            ).fetchone()
        if row is None:
            return None
        return _workflow_from_json(
            self._decrypt(str(tenant_id), str(row["encrypted_definition_json"]))
        )

    def delete(self, tenant_id: str, workflow_id: str) -> bool:
        """Delete one stored workflow definition.

        Example:
            >>> store = StudioWorkflowStore(path=":memory:")
            >>> store.delete("tenant-a", "missing")
            False
        """

        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM studio_workflows WHERE tenant_id = ? AND workflow_id = ?",
                (str(tenant_id), str(workflow_id)),
            )
        return bool(cursor.rowcount)

    def prune(self, *, max_age_seconds: int) -> int:
        """Delete workflow rows older than the max age threshold.

        Example:
            >>> store = StudioWorkflowStore(path=":memory:")
            >>> store.prune(max_age_seconds=3600)
            0
        """

        cutoff = time.time() - float(max_age_seconds)
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM studio_workflows WHERE updated_at < ?", (cutoff,))
        return int(cursor.rowcount)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS studio_workflows (
                    workflow_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    encrypted_definition_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_studio_workflows_tenant_updated ON studio_workflows(tenant_id, updated_at)"
            )

    def _encrypt(self, tenant_id: str, payload: str) -> str:
        encrypted = EncryptionLayer.encrypt(
            payload, EncryptionLayer.derive_key(tenant_id, self._master_key)
        )
        return json.dumps(
            {
                "ciphertext_b64": encrypted.ciphertext_b64,
                "nonce_b64": encrypted.nonce_b64,
                "tag_b64": encrypted.tag_b64,
            },
            separators=(",", ":"),
        )

    def _decrypt(self, tenant_id: str, payload: str) -> str:
        return EncryptionLayer.decrypt(
            json.loads(payload),
            EncryptionLayer.derive_key(tenant_id, self._master_key),
        )


def _workflow_to_json(workflow: WorkflowDefinition, *, workflow_id: str) -> str:
    return json.dumps(
        {
            "workflow_id": workflow_id,
            "name": workflow.name,
            "steps": [
                {
                    "step_id": step.step_id,
                    "agent": step.agent,
                    "action": step.action,
                    "config": dict(step.config),
                    "dependencies": list(step.dependencies),
                }
                for step in workflow.steps
            ],
            "metadata": dict(workflow.metadata),
            "version": workflow.version,
            "created_at": workflow.created_at,
        },
        separators=(",", ":"),
    )


def _workflow_from_json(payload: str) -> WorkflowDefinition:
    raw = json.loads(payload)
    steps = [
        Step(
            step_id=str(step.get("step_id") or ""),
            agent=str(step.get("agent") or ""),
            action=str(step.get("action") or ""),
            config=dict(step.get("config") or {}),
            dependencies=[str(dep) for dep in step.get("dependencies", [])],
        )
        for step in raw.get("steps", [])
        if isinstance(step, dict)
    ]
    return WorkflowDefinition(
        workflow_id=str(raw.get("workflow_id") or _workflow_id()),
        name=str(raw.get("name") or "Studio Workflow"),
        steps=steps,
        metadata=dict(raw.get("metadata") or {}),
        version=int(raw.get("version") or 1),
        created_at=float(raw.get("created_at") or time.time()),
    )
