"""Tests for Studio workflow serialization and API endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from archon.core.approval_gate import ApprovalGate
from archon.core.orchestrator import OrchestrationResult
from archon.interfaces.api.server import app
from archon.studio.execution import _load_openclaw_config
from archon.studio.runtime import WorkflowRunBroker, execute_workflow_run
from archon.studio.workflow_serializer import deserialize, serialize, validate

_JWT_SECRET = "archon-dev-secret-change-me-32-bytes"


def _auth_token(*, tenant: str = "tenant-studio", tier: str = "business") -> str:
    return jwt.encode(
        {"sub": tenant, "tier": tier},
        os.environ.get("ARCHON_JWT_SECRET", _JWT_SECRET),
        algorithm="HS256",
    )


def _auth_headers(*, tenant: str = "tenant-studio", tier: str = "business") -> dict[str, str]:
    return {"Authorization": f"Bearer {_auth_token(tenant=tenant, tier=tier)}"}


@pytest.fixture(autouse=True)
def _jwt_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_JWT_SECRET", _JWT_SECRET)


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


def _receive_ws_json_or_fail(websocket) -> dict[str, object]:
    try:
        frame = websocket.receive_json()
    except WebSocketDisconnect as exc:
        pytest.fail(f"WS disconnected with code {exc.code}: {exc.reason}")
    if not isinstance(frame, dict):
        pytest.fail(f"Unexpected websocket frame: {frame!r}")
    return frame


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


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
            {
                "step_id": "a",
                "agent": "ResearcherAgent",
                "action": "a",
                "config": {"node_type": "AgentNode"},
                "dependencies": ["b"],
            },
            {
                "step_id": "b",
                "agent": "ResearcherAgent",
                "action": "b",
                "config": {"node_type": "OutputNode"},
                "dependencies": ["a"],
            },
        ],
        "metadata": {},
        "version": 1,
        "created_at": time.time(),
    }
    orphan = {
        "workflow_id": "wf-orphan",
        "name": "Orphan",
        "steps": [
            {
                "step_id": "a",
                "agent": "ResearcherAgent",
                "action": "a",
                "config": {"node_type": "AgentNode"},
                "dependencies": [],
            },
            {
                "step_id": "b",
                "agent": "OutputNode",
                "action": "b",
                "config": {"node_type": "OutputNode"},
                "dependencies": [],
            },
        ],
        "metadata": {},
        "version": 1,
        "created_at": time.time(),
    }
    missing_agent = {
        "workflow_id": "wf-missing",
        "name": "Missing",
        "steps": [
            {
                "step_id": "a",
                "agent": "MissingAgent",
                "action": "a",
                "config": {"node_type": "AgentNode"},
                "dependencies": [],
            },
            {
                "step_id": "b",
                "agent": "OutputNode",
                "action": "b",
                "config": {"node_type": "OutputNode"},
                "dependencies": ["a"],
            },
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
            frame = _receive_ws_json_or_fail(websocket)
            assert frame["type"] in {"workflow_started", "step_started"}

        deleted = client.delete(f"/studio/workflows/{workflow_id}", headers=_auth_headers())
        assert deleted.status_code == 200
        missing = client.get(f"/studio/workflows/{workflow_id}", headers=_auth_headers())
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_workflow_run_broker_subscribe_waits_for_terminal_workflow_event() -> None:
    broker = WorkflowRunBroker()
    run = broker.create_run("tenant-a", "workflow-a")

    await broker.publish(run.run_id, {"type": "step_completed", "step_id": "node-a"})
    await broker.publish(run.run_id, {"type": "workflow_completed", "terminal": True})

    events: list[str] = []
    async for event in broker.subscribe(run.run_id):
        events.append(str(event["type"]))

    assert events == ["step_completed", "workflow_completed"]


@pytest.mark.asyncio
async def test_execute_workflow_run_openclaw_backend_dispatches_remote_agent_step(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ARCHON_STUDIO_EXECUTION_LAYER", "openclaw")
    monkeypatch.setenv("ARCHON_OPENCLAW_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OPENCLAW_STATE_DIR", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_CONFIG_PATH", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_BASE_URL", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_TOKEN", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_AGENT_ID", raising=False)

    _write_json(
        tmp_path / "openclaw.json",
        {
            "agents": {
                "list": [
                    {"id": "worker"},
                    {"id": "dev", "default": True},
                ]
            },
            "gateway": {
                "bind": "loopback",
                "port": 18791,
                "auth": {"mode": "token", "token": "openclaw-discovered-token"},
            },
        },
    )

    captured: dict[str, object] = {}

    async def fake_request_response(self, *, step, workflow, run_id, tenant_id, prior_results):  # type: ignore[no-untyped-def]
        captured["step_id"] = step.step_id
        captured["workflow_id"] = workflow.workflow_id
        captured["run_id"] = run_id
        captured["tenant_id"] = tenant_id
        captured["prior_results"] = list(prior_results)
        captured["agent_id"] = self.config.agent_id
        captured["base_url"] = self.config.base_url
        return {"output_text": "OpenClaw finished research and returned a concise result."}

    monkeypatch.setattr(
        "archon.studio.execution.OpenClawStudioStepExecutor._request_response",
        fake_request_response,
    )

    class _FakeOrchestrator:
        def __init__(self) -> None:
            self.approval_gate = ApprovalGate(auto_approve_in_test=True)

        async def execute(
            self,
            *,
            goal: str,
            mode: str,
            context: dict[str, object],
            event_sink=None,
            **_kwargs,
        ) -> OrchestrationResult:
            del event_sink
            captured["goal"] = goal
            captured["mode"] = mode
            captured["context"] = context
            return OrchestrationResult(
                task_id="task-studio-openclaw",
                goal="Studio run",
                mode="debate",
                final_answer="final synthesis",
                confidence=93,
                budget={"spent_usd": 0.02},
                debate={"rounds": []},
                growth=None,
            )

    workflow = serialize(_sample_nodes(), _sample_edges())
    broker = WorkflowRunBroker()
    run = broker.create_run("tenant-studio", workflow.workflow_id)

    task = asyncio.create_task(
        execute_workflow_run(
            broker=broker,
            run_id=run.run_id,
            workflow=workflow,
            orchestrator=_FakeOrchestrator(),
            tenant_id="tenant-studio",
        )
    )
    events: list[dict[str, object]] = []
    async for event in broker.subscribe(run.run_id):
        events.append(event)
    await task

    step_events = [event for event in events if event.get("type") == "step_completed"]
    assert any(event.get("executor") == "openclaw" for event in step_events)
    assert any(event.get("executor") == "local" for event in step_events)
    assert events[-1]["type"] == "workflow_completed"
    assert captured["step_id"] == "agent-a"
    assert captured["tenant_id"] == "tenant-studio"
    assert captured["agent_id"] == "dev"
    assert captured["base_url"] == "http://127.0.0.1:18791"
    assert captured["mode"] == "debate"
    assert "Executed workflow step results" in str(captured["goal"])
    context = captured["context"]
    assert isinstance(context, dict)
    assert context["execution_layer"] == "openclaw"
    assert context["step_results"][0]["output_text"] == (
        "OpenClaw finished research and returned a concise result."
    )


@pytest.mark.asyncio
async def test_execute_workflow_run_reports_terminal_failure_for_bad_openclaw_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ARCHON_STUDIO_EXECUTION_LAYER", "openclaw")
    monkeypatch.setenv("ARCHON_OPENCLAW_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OPENCLAW_STATE_DIR", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_CONFIG_PATH", raising=False)
    monkeypatch.setenv("ARCHON_OPENCLAW_BASE_URL", "http://openclaw.local:18789")
    monkeypatch.delenv("ARCHON_OPENCLAW_TOKEN", raising=False)

    class _FakeOrchestrator:
        def __init__(self) -> None:
            self.approval_gate = ApprovalGate(auto_approve_in_test=True)

        async def execute(self, **_kwargs):  # type: ignore[no-untyped-def]
            pytest.fail("orchestrator.execute should not be called when OpenClaw config is invalid")

    workflow = serialize(_sample_nodes(), _sample_edges())
    broker = WorkflowRunBroker()
    run = broker.create_run("tenant-studio", workflow.workflow_id)

    task = asyncio.create_task(
        execute_workflow_run(
            broker=broker,
            run_id=run.run_id,
            workflow=workflow,
            orchestrator=_FakeOrchestrator(),
            tenant_id="tenant-studio",
        )
    )
    events = [event async for event in broker.subscribe(run.run_id)]
    await task

    assert events[-1]["type"] == "workflow_failed"
    assert events[-1]["terminal"] is True
    assert "ARCHON_OPENCLAW_TOKEN" in str(events[-1]["message"])


def test_load_openclaw_config_discovers_local_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARCHON_OPENCLAW_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OPENCLAW_STATE_DIR", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_CONFIG_PATH", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_BASE_URL", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_TOKEN", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_AGENT_ID", raising=False)

    _write_json(
        tmp_path / "openclaw.json",
        {
            "agents": {
                "list": [
                    {"id": "worker"},
                    {"id": "dev", "default": True},
                ]
            },
            "gateway": {
                "bind": "loopback",
                "port": 19090,
                "auth": {"mode": "token", "token": "state-token"},
            },
        },
    )

    config = _load_openclaw_config()

    assert config.base_url == "http://127.0.0.1:19090"
    assert config.token == "state-token"
    assert config.agent_id == "dev"


def test_load_openclaw_config_uses_launcher_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARCHON_OPENCLAW_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OPENCLAW_STATE_DIR", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_CONFIG_PATH", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_BASE_URL", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_TOKEN", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_AGENT_ID", raising=False)

    _write_json(
        tmp_path / "openclaw.json",
        {
            "agents": {"list": [{"id": "worker"}]},
            "gateway": {"bind": "loopback", "auth": {"mode": "token"}},
        },
    )
    (tmp_path / "gateway.cmd").write_text(
        '@echo off\nset "OPENCLAW_GATEWAY_PORT=18888"\nset "OPENCLAW_GATEWAY_TOKEN=launcher-token"\n',
        encoding="utf-8",
    )

    config = _load_openclaw_config()

    assert config.base_url == "http://127.0.0.1:18888"
    assert config.token == "launcher-token"
    assert config.agent_id == "worker"


def test_load_openclaw_config_prefers_explicit_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARCHON_OPENCLAW_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OPENCLAW_STATE_DIR", raising=False)
    monkeypatch.delenv("ARCHON_OPENCLAW_CONFIG_PATH", raising=False)
    monkeypatch.setenv("ARCHON_OPENCLAW_BASE_URL", "http://manual-host:19999")
    monkeypatch.setenv("ARCHON_OPENCLAW_TOKEN", "manual-token")
    monkeypatch.setenv("ARCHON_OPENCLAW_AGENT_ID", "manual-agent")

    _write_json(
        tmp_path / "openclaw.json",
        {
            "agents": {"list": [{"id": "worker", "default": True}]},
            "gateway": {
                "bind": "loopback",
                "port": 19090,
                "auth": {"mode": "token", "token": "state-token"},
            },
        },
    )

    config = _load_openclaw_config()

    assert config.base_url == "http://manual-host:19999"
    assert config.token == "manual-token"
    assert config.agent_id == "manual-agent"


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
                {
                    "step_id": "a",
                    "agent": "ResearcherAgent",
                    "action": "research",
                    "config": {"node_type": "AgentNode"},
                    "dependencies": [],
                },
            ],
            "output_unreachable",
        ),
        (
            [
                {
                    "step_id": "a",
                    "agent": "ResearcherAgent",
                    "action": "research",
                    "config": {"node_type": "AgentNode"},
                    "dependencies": [],
                },
                {
                    "step_id": "b",
                    "agent": "OutputNode",
                    "action": "emit",
                    "config": {"node_type": "OutputNode"},
                    "dependencies": ["missing"],
                },
            ],
            "missing_dependency",
        ),
        (
            [
                {
                    "step_id": "a",
                    "agent": "Unknown",
                    "action": "research",
                    "config": {"node_type": "AgentNode"},
                    "dependencies": [],
                },
                {
                    "step_id": "b",
                    "agent": "OutputNode",
                    "action": "emit",
                    "config": {"node_type": "OutputNode"},
                    "dependencies": ["a"],
                },
            ],
            "missing_agent_class",
        ),
        (
            [
                {
                    "step_id": "a",
                    "agent": "ResearcherAgent",
                    "action": "research",
                    "config": {"node_type": "AgentNode"},
                    "dependencies": [],
                },
                {
                    "step_id": "a",
                    "agent": "OutputNode",
                    "action": "emit",
                    "config": {"node_type": "OutputNode"},
                    "dependencies": [],
                },
            ],
            "duplicate",
        ),
        (
            [
                {
                    "step_id": "a",
                    "agent": "ResearcherAgent",
                    "action": "research",
                    "config": {"node_type": "AgentNode"},
                    "dependencies": ["b"],
                },
                {
                    "step_id": "b",
                    "agent": "OutputNode",
                    "action": "emit",
                    "config": {"node_type": "OutputNode"},
                    "dependencies": ["a"],
                },
            ],
            "cycle",
        ),
        (
            [
                {
                    "step_id": "isolated",
                    "agent": "ResearcherAgent",
                    "action": "research",
                    "config": {"node_type": "AgentNode"},
                    "dependencies": [],
                },
                {
                    "step_id": "output",
                    "agent": "OutputNode",
                    "action": "emit",
                    "config": {"node_type": "OutputNode"},
                    "dependencies": [],
                },
            ],
            "orphan",
        ),
    ],
)
def test_workflow_serializer_validation_matrix(
    steps: list[dict[str, object]], expected_code: str
) -> None:
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
