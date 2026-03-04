"""API contract tests for task orchestration modes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from archon.interfaces.api.server import app


def test_post_tasks_debate_mode_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    with TestClient(app) as client:
        response = client.post(
            "/v1/tasks",
            json={
                "goal": "Draft a migration rollout plan",
                "mode": "debate",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "debate"
    assert payload["debate"] is not None
    assert payload["growth"] is None
    assert isinstance(payload["debate"]["rounds"], list)
    assert len(payload["debate"]["rounds"]) == 6
    assert isinstance(payload["budget"], dict)
    assert isinstance(payload["confidence"], int)


def test_post_tasks_growth_mode_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    with TestClient(app) as client:
        response = client.post(
            "/v1/tasks",
            json={
                "goal": "Increase qualified leads in Indian pharmacy SMBs",
                "mode": "growth",
                "context": {
                    "market": "India",
                    "sector": "pharmacy",
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "growth"
    assert payload["growth"] is not None
    assert payload["debate"] is None
    assert "agent_reports" in payload["growth"]
    assert "recommended_actions" in payload["growth"]
    assert len(payload["growth"]["agent_reports"]) == 7
    assert len(payload["growth"]["recommended_actions"]) >= 7
    assert isinstance(payload["confidence"], int)

