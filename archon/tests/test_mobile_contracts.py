"""Mobile interface contract tests for schemas and WS/hook behavior expectations."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, ValidationError, field_validator

from archon.interfaces.api.server import app

_MOBILE_HOOK_PATH = Path("archon/interfaces/mobile/useARCHONMobile.ts")


class SessionStateModel(BaseModel):
    session_id: str
    tenant_id: str
    tier: str


class ChatMessageModel(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionRestoredFrame(BaseModel):
    type: Literal["session_restored"]
    session: SessionStateModel
    messages: list[ChatMessageModel]


class AssistantTokenFrame(BaseModel):
    type: Literal["assistant_token"]
    token: str


class DoneFrame(BaseModel):
    type: Literal["done"]
    message: ChatMessageModel


class InvoiceLineItemSchema(BaseModel):
    description: str
    quantity: float
    unit_price: float
    total: float


class InvoiceCardSchema(BaseModel):
    due_date: str
    line_items: list[InvoiceLineItemSchema]
    total: float
    currency: str | None = None
    invoice_number: str | None = None


class ReportSectionSchema(BaseModel):
    heading: str
    body: str


class ReportCardSchema(BaseModel):
    title: str
    summary: str
    sections: list[ReportSectionSchema]


class ComparisonRowSchema(BaseModel):
    label: str
    values: list[str | float | int]


class ComparisonTableSchema(BaseModel):
    headers: list[str]
    rows: list[ComparisonRowSchema]
    winner_column: int | None = None

    @field_validator("headers")
    @classmethod
    def _validate_headers(cls, value: list[str]) -> list[str]:
        if len(value) < 2:
            raise ValueError("headers must include row label + at least one comparison column")
        return value

    @field_validator("winner_column")
    @classmethod
    def _validate_winner(cls, value: int | None, info):
        if value is None:
            return value
        headers = info.data.get("headers") or []
        if value < 1 or value >= len(headers):
            raise ValueError("winner_column must point at one of the value columns")
        return value


class TimelineStepSchema(BaseModel):
    title: str
    date: str
    detail: str | None = None


class TimelineCardSchema(BaseModel):
    steps: list[TimelineStepSchema]
    title: str | None = None

    @field_validator("steps")
    @classmethod
    def _validate_steps(cls, value: list[TimelineStepSchema]) -> list[TimelineStepSchema]:
        if not value:
            raise ValueError("steps cannot be empty")
        return value


class MockAsyncStorage:
    """Tiny in-memory adapter mirroring AsyncStorage multiSet/multiGet semantics."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def multi_set(self, rows: list[tuple[str, str]]) -> None:
        for key, value in rows:
            self._store[key] = value

    def multi_get(self, keys: list[str]) -> list[tuple[str, str | None]]:
        return [(key, self._store.get(key)) for key in keys]


def _mobile_source() -> str:
    return _MOBILE_HOOK_PATH.read_text(encoding="utf-8")


def _extract_storage_keys(source: str) -> tuple[str, str]:
    token_match = re.search(r'export const TOKEN_KEY\s*=\s*"([^"]+)"', source)
    session_match = re.search(r'export const SESSION_KEY\s*=\s*"([^"]+)"', source)
    assert token_match is not None
    assert session_match is not None
    return token_match.group(1), session_match.group(1)


def _reduce_mobile_event_py(
    current: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    next_approvals = list(current["pendingApprovals"])
    next_agents = dict(current["agentStates"])
    next_cost = dict(current["costState"])

    event_type = str(event.get("type", "")).lower()

    if event_type == "agent_start":
        agent_name = str(event.get("agent") or event.get("agent_name") or "").strip()
        if agent_name:
            next_agents[agent_name] = {
                "status": "thinking",
                "startedAt": float(event.get("started_at", 0) or 0),
            }

    if event_type in {"agent_end", "growth_agent_completed"}:
        agent_name = str(event.get("agent") or event.get("agent_name") or "").strip()
        if agent_name:
            previous = next_agents.get(agent_name, {})
            next_agents[agent_name] = {
                "status": str(event.get("status") or "done").lower(),
                "startedAt": float(event.get("started_at", previous.get("startedAt", 0)) or 0),
            }

    if event_type == "done":
        for agent_name, payload in list(next_agents.items()):
            if payload.get("status") == "thinking":
                next_agents[agent_name] = {
                    **payload,
                    "status": "done",
                }

    if event_type == "cost_update":
        spent = float(event.get("spent", event.get("total_spent", next_cost.get("spent", 0))) or 0)
        budget = float(event.get("budget", event.get("limit", next_cost.get("budget", 0))) or 0)
        point = {"spent": spent, "budget": budget, "ts": 1.0}
        history = list(next_cost.get("history", []))
        next_cost = {
            "spent": spent,
            "budget": budget,
            "history": (history + [point])[-20:],
        }

    if event_type == "approval_required":
        request_id = str(event.get("request_id") or event.get("action_id") or "").strip()
        if request_id:
            normalized = {
                **event,
                "request_id": request_id,
                "action_id": request_id,
            }
            index = -1
            for idx, item in enumerate(next_approvals):
                if item.get("action_id") == request_id:
                    index = idx
                    break
            if index >= 0:
                next_approvals[index] = normalized
            else:
                next_approvals.append(normalized)

    if event_type in {"approval_result", "approval_resolved"}:
        request_id = str(event.get("request_id") or event.get("action_id") or "").strip()
        if request_id:
            next_approvals = [item for item in next_approvals if item.get("action_id") != request_id]

    return {
        "pendingApprovals": next_approvals,
        "agentStates": next_agents,
        "costState": next_cost,
    }


def _save_session_py(storage: MockAsyncStorage, token_key: str, session_key: str, token: str, session_id: str) -> None:
    storage.multi_set([(token_key, token), (session_key, session_id)])


def _load_session_py(storage: MockAsyncStorage, token_key: str, session_key: str) -> dict[str, str]:
    rows = dict(storage.multi_get([token_key, session_key]))
    return {
        "token": str(rows.get(token_key) or "").strip(),
        "sessionId": str(rows.get(session_key) or "").strip(),
    }


@pytest.fixture(autouse=True)
def _openrouter_key_fixture() -> None:
    previous = os.environ.get("OPENROUTER_API_KEY")
    previous_jwt = os.environ.get("ARCHON_JWT_SECRET")
    os.environ["OPENROUTER_API_KEY"] = previous or "mobile-contract-openrouter-key"
    os.environ["ARCHON_JWT_SECRET"] = previous_jwt or "archon-dev-secret-change-me-32-bytes"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("OPENROUTER_API_KEY", None)
        else:
            os.environ["OPENROUTER_API_KEY"] = previous
        if previous_jwt is None:
            os.environ.pop("ARCHON_JWT_SECRET", None)
        else:
            os.environ["ARCHON_JWT_SECRET"] = previous_jwt


def test_mobile_websocket_message_shapes_match_server_contract() -> None:
    """Anonymous webchat flow emits frames compatible with mobile hook expectations."""

    with TestClient(app) as client:
        issued = client.post("/webchat/token", json={})
        assert issued.status_code == 200
        body = issued.json()
        token = body["token"]
        session_id = body["session"]["session_id"]

        with client.websocket_connect(f"/webchat/ws/{session_id}?token={token}") as websocket:
            restored = websocket.receive_json()
            SessionRestoredFrame.model_validate(restored)

            websocket.send_json({"type": "message", "content": "Mobile contract smoke"})

            token_seen = False
            done_seen = False
            for _ in range(500):
                frame = websocket.receive_json()
                frame_type = str(frame.get("type", ""))
                if frame_type == "assistant_token":
                    AssistantTokenFrame.model_validate(frame)
                    token_seen = True
                if frame_type == "done":
                    DoneFrame.model_validate(frame)
                    done_seen = True
                    break

    assert token_seen is True
    assert done_seen is True


def test_invoice_card_schema_validation() -> None:
    payload = {
        "invoice_number": "INV-101",
        "due_date": "2026-03-20",
        "currency": "USD",
        "line_items": [
            {"description": "Discovery", "quantity": 2, "unit_price": 300, "total": 600},
            {"description": "Implementation", "quantity": 5, "unit_price": 450, "total": 2250},
        ],
        "total": 2850,
    }
    parsed = InvoiceCardSchema.model_validate(payload)
    assert parsed.total == 2850
    assert len(parsed.line_items) == 2

    with pytest.raises(ValidationError):
        InvoiceCardSchema.model_validate({"due_date": "2026-03-20", "line_items": [], "currency": "USD"})


def test_report_card_schema_validation() -> None:
    payload = {
        "title": "Quarterly Growth Review",
        "summary": "Pipeline quality improved across inbound and outbound channels.",
        "sections": [
            {"heading": "Wins", "body": "SQL conversion rate improved by 18%."},
            {"heading": "Risks", "body": "Lead source concentration remains high."},
        ],
    }
    parsed = ReportCardSchema.model_validate(payload)
    assert parsed.title.startswith("Quarterly")
    assert len(parsed.sections) == 2

    with pytest.raises(ValidationError):
        ReportCardSchema.model_validate({"summary": "Missing title", "sections": []})


def test_comparison_table_schema_validation() -> None:
    payload = {
        "headers": ["Metric", "Plan A", "Plan B"],
        "rows": [
            {"label": "Cost", "values": [1200, 980]},
            {"label": "Time", "values": ["6w", "5w"]},
        ],
        "winner_column": 2,
    }
    parsed = ComparisonTableSchema.model_validate(payload)
    assert parsed.winner_column == 2
    assert len(parsed.rows) == 2

    with pytest.raises(ValidationError):
        ComparisonTableSchema.model_validate(
            {
                "headers": ["Metric"],
                "rows": [{"label": "Cost", "values": [1200]}],
                "winner_column": 1,
            }
        )


def test_timeline_card_schema_validation() -> None:
    payload = {
        "title": "Launch Plan",
        "steps": [
            {"title": "Research", "date": "2026-03-08", "detail": "Collect user constraints"},
            {"title": "Build", "date": "2026-03-12"},
            {"title": "Deploy", "date": "2026-03-20", "detail": "Roll out in waves"},
        ],
    }
    parsed = TimelineCardSchema.model_validate(payload)
    assert len(parsed.steps) == 3

    with pytest.raises(ValidationError):
        TimelineCardSchema.model_validate({"title": "Empty", "steps": []})


def test_use_archon_mobile_dispatch_contract() -> None:
    """Reducer contract: core event transitions stay aligned with mobile hook expectations."""

    source = _mobile_source()
    for snippet in [
        'type === "agent_start"',
        'type === "cost_update"',
        'type === "approval_required"',
        'type === "done"',
        'type === "approval_result" || type === "approval_resolved"',
    ]:
        assert snippet in source

    state = {
        "pendingApprovals": [],
        "agentStates": {},
        "costState": {"spent": 0.0, "budget": 0.0, "history": []},
    }

    state = _reduce_mobile_event_py(
        state,
        {"type": "agent_start", "agent": "ProspectorAgent", "started_at": 111.1},
    )
    assert state["agentStates"]["ProspectorAgent"]["status"] == "thinking"

    state = _reduce_mobile_event_py(
        state,
        {"type": "cost_update", "spent": 1.25, "budget": 20.0},
    )
    assert state["costState"]["spent"] == 1.25
    assert state["costState"]["budget"] == 20.0
    assert len(state["costState"]["history"]) == 1

    state = _reduce_mobile_event_py(
        state,
        {
            "type": "approval_required",
            "request_id": "approve-1",
            "action": "external_api_call",
        },
    )
    assert len(state["pendingApprovals"]) == 1
    assert state["pendingApprovals"][0]["action_id"] == "approve-1"

    state = _reduce_mobile_event_py(state, {"type": "done"})
    assert state["agentStates"]["ProspectorAgent"]["status"] == "done"


def test_token_persistence_roundtrip_with_mocked_storage() -> None:
    """Storage contract: token/session keys roundtrip through AsyncStorage-style APIs."""

    source = _mobile_source()
    assert "AsyncStorage.multiSet" in source
    assert "AsyncStorage.multiGet" in source

    token_key, session_key = _extract_storage_keys(source)
    storage = MockAsyncStorage()

    _save_session_py(storage, token_key, session_key, "token-abc", "session-xyz")
    loaded = _load_session_py(storage, token_key, session_key)

    assert loaded == {"token": "token-abc", "sessionId": "session-xyz"}
