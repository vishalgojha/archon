"""Tests for Studio workflow serialization and API endpoints."""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from archon.core.orchestrator import OrchestrationResult
from archon.interfaces.api.server import app
from archon.studio.workflow_serializer import deserialize, serialize, validate


def _auth_token(*, tenant: str = "tenant-studio", tier: str = "business") -> str:
    return jwt.encode(
        {"sub": tenant, "tier": tier},
        "archon-dev-secret-change-me-32-bytes",
        algorithm="HS256",
    )


def _auth_headers(*, tenant: str = "tenant-studio", tier: str = "business") -> dict[str, str]:
    return {"Authorization": f"Bearer {_auth_token(tenant=tenant, tier=tier)}"}


def _tmp_db(name: str) -> Path:
    root = Path("archon/tests/_tmp_studio")
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{name}-{uuid.uuid4().hex[:8]}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "studio.sqlite3"


def _sample_nodes() -> list[dict[str, object]]:
    return [
        {
            "id": "agent-a",
            "type": "AgentNode",
            "position": {"x": 0, "y": 0},
            "data": {"agent_class": "ResearcherAgent", "action": "research"},
        },
        {
            "id": "output",
            "type": "OutputNode",
            "position": {"x": 240, "y": 0},
            "data": {"action": "emit"},
        },
    ]


def _sample_edges() -> list[dict[str, object]]:
    return [{"id": "e1", "source": "agent-a", "target": "output", "label": "text"}]


def test_workflow_serializer_roundtrip_preserves_nodes_and_edges() -> None:
    workflow = serialize(_sample_nodes(), _sample_edges())
    restored = deserialize(workflow)

    assert restored["nodes"] == _sample_nodes()
    assert restored["edges"] == _sample_edges()


def test_workflow_serializer_validate_catches_cycle_orphan_and_missing_agent() -> None:
    cycle = {
        "workflow_id": "wf-cycle",
        "name": "Cycle",
        "steps": [
            {"step_id": "a", "agent": "ResearcherAgent", "action": "a", "config": {"node_type": "AgentNode"}, "dependencies": ["b"]},
            {"step_id": "b", "agent": "ResearcherAgent", "action": "b", "config": {"node_type": "OutputNode"}, "dependencies": ["a"]},
        ],
        "metadata": {},
        "version": 1,
        "created_at": time.time(),
    }
    orphan = {
        "workflow_id": "wf-orphan",
        "name": "Orphan",
        "steps": [
            {"step_id": "a", "agent": "ResearcherAgent", "action": "a", "config": {"node_type": "AgentNode"}, "dependencies": []},
            {"step_id": "b", "agent": "OutputNode", "action": "b", "config": {"node_type": "OutputNode"}, "dependencies": []},
        ],
        "metadata": {},
        "version": 1,
        "created_at": time.time(),
    }
    missing_agent = {
        "workflow_id": "wf-missing",
        "name": "Missing",
        "steps": [
            {"step_id": "a", "agent": "MissingAgent", "action": "a", "config": {"node_type": "AgentNode"}, "dependencies": []},
            {"step_id": "b", "agent": "OutputNode", "action": "b", "config": {"node_type": "OutputNode"}, "dependencies": ["a"]},
        ],
        "metadata": {},
        "version": 1,
        "created_at": time.time(),
    }

    cycle_errors = validate(cycle)
    orphan_errors = validate(orphan)
    missing_errors = validate(missing_agent)

    assert any(error.code == "cycle" for error in cycle_errors)
    assert any(error.code == "orphan" for error in orphan_errors)
    assert any(error.code == "missing_agent_class" for error in missing_errors)


def test_studio_api_save_load_delete_and_run_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "studio-openrouter-key")
    monkeypatch.setenv("ARCHON_STUDIO_DB", str(_tmp_db("studio-api")))
    token = _auth_token()

    with TestClient(app) as client:
        workflow = serialize(_sample_nodes(), _sample_edges())
        payload = {
            "workflow_id": workflow.workflow_id,
            "name": "Studio API Workflow",
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
        }

        save = client.post("/studio/workflows", json=payload, headers=_auth_headers())
        assert save.status_code == 200
        workflow_id = save.json()["workflow_id"]

        listing = client.get("/studio/workflows", headers=_auth_headers())
        assert listing.status_code == 200
        assert listing.json()[0]["id"] == workflow_id

        fetched = client.get(f"/studio/workflows/{workflow_id}", headers=_auth_headers())
        assert fetched.status_code == 200
        assert fetched.json()["workflow_id"] == workflow_id

        async def fake_execute(*, goal: str, mode: str, context: dict[str, object]):  # type: ignore[no-untyped-def]
            del goal, mode, context
            return OrchestrationResult(
                task_id="task-studio",
                goal="Studio run",
                mode="debate",
                final_answer="workflow executed",
                confidence=91,
                budget={"spent_usd": 0.01},
                debate={"rounds": []},
                growth=None,
            )

        monkeypatch.setattr(app.state.orchestrator, "execute", fake_execute)

        run = client.post("/studio/run", json={"workflow": fetched.json()}, headers=_auth_headers())
        assert run.status_code == 200
        ws_path = f"{run.json()['websocket_path']}?token={token}"

        with client.websocket_connect(ws_path) as websocket:
            frame = websocket.receive_json()
            assert frame["type"] in {"workflow_started", "step_started"}

        deleted = client.delete(f"/studio/workflows/{workflow_id}", headers=_auth_headers())
        assert deleted.status_code == 200
        missing = client.get(f"/studio/workflows/{workflow_id}", headers=_auth_headers())
        assert missing.status_code == 404


@pytest.mark.parametrize(
    "node_type",
    ["AgentNode", "DebateNode", "ApprovalNode", "ConditionNode", "LoopNode", "OutputNode"],
)
def test_workflow_serializer_node_type_matrix(node_type: str) -> None:
    nodes = [
        {
            "id": "node-a",
            "type": node_type,
            "position": {"x": 0, "y": 0},
            "data": {
                "agent_class": "ResearcherAgent" if node_type == "AgentNode" else node_type,
                "action": node_type.lower(),
            },
        },
        {
            "id": "output",
            "type": "OutputNode",
            "position": {"x": 180, "y": 0},
            "data": {"action": "emit"},
        },
    ]
    edges = [{"id": "e1", "source": "node-a", "target": "output", "label": "data"}]

    workflow = serialize(nodes, edges)
    restored = deserialize(workflow)

    assert restored["nodes"][0]["type"] == node_type
    assert restored["edges"][0]["source"] == "node-a"


@pytest.mark.parametrize(
    ("steps", "expected_code"),
    [
        (
            [
                {"step_id": "a", "agent": "ResearcherAgent", "action": "research", "config": {"node_type": "AgentNode"}, "dependencies": []},
            ],
            "output_unreachable",
        ),
        (
            [
                {"step_id": "a", "agent": "ResearcherAgent", "action": "research", "config": {"node_type": "AgentNode"}, "dependencies": []},
                {"step_id": "b", "agent": "OutputNode", "action": "emit", "config": {"node_type": "OutputNode"}, "dependencies": ["missing"]},
            ],
            "missing_dependency",
        ),
        (
            [
                {"step_id": "a", "agent": "Unknown", "action": "research", "config": {"node_type": "AgentNode"}, "dependencies": []},
                {"step_id": "b", "agent": "OutputNode", "action": "emit", "config": {"node_type": "OutputNode"}, "dependencies": ["a"]},
            ],
            "missing_agent_class",
        ),
        (
            [
                {"step_id": "a", "agent": "ResearcherAgent", "action": "research", "config": {"node_type": "AgentNode"}, "dependencies": []},
                {"step_id": "a", "agent": "OutputNode", "action": "emit", "config": {"node_type": "OutputNode"}, "dependencies": []},
            ],
            "duplicate",
        ),
        (
            [
                {"step_id": "a", "agent": "ResearcherAgent", "action": "research", "config": {"node_type": "AgentNode"}, "dependencies": ["b"]},
                {"step_id": "b", "agent": "OutputNode", "action": "emit", "config": {"node_type": "OutputNode"}, "dependencies": ["a"]},
            ],
            "cycle",
        ),
        (
            [
                {"step_id": "isolated", "agent": "ResearcherAgent", "action": "research", "config": {"node_type": "AgentNode"}, "dependencies": []},
                {"step_id": "output", "agent": "OutputNode", "action": "emit", "config": {"node_type": "OutputNode"}, "dependencies": []},
            ],
            "orphan",
        ),
    ],
)
def test_workflow_serializer_validation_matrix(steps: list[dict[str, object]], expected_code: str) -> None:
    payload = {
        "workflow_id": "wf-matrix",
        "name": "Matrix",
        "steps": steps,
        "metadata": {},
        "version": 1,
        "created_at": time.time(),
    }

    errors = validate(payload)

    assert any(error.code == expected_code for error in errors)
