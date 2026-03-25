"""Shared per-session swarm memory with SQLite persistence."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from typing import Any

from archon.swarm.types import AgentResult, Plan


class SwarmMemory:
    """In-memory context shared across swarm agents, persisted on completion."""

    def __init__(self, session_id: str, *, db_path: str = "archon_swarm.sqlite3") -> None:
        self.session_id = session_id
        self.db_path = db_path
        self.goal: str = ""
        self.plan: Plan | None = None
        self.agent_outputs: dict[str, AgentResult] = {}
        self.shared_context: dict[str, Any] = {}
        self._ensure_schema()

    def set_goal(self, goal: str) -> None:
        self.goal = goal

    def record_plan(self, plan: Plan) -> None:
        self.plan = plan

    def record_output(self, agent_id: str, result: AgentResult) -> None:
        self.agent_outputs[agent_id] = result

    def update_shared(self, key: str, value: Any) -> None:
        self.shared_context[key] = value

    def get_context_for_agent(self, agent_type: str) -> dict[str, Any]:
        """Return filtered context for a specific agent type."""
        context: dict[str, Any] = {
            "goal": self.goal,
            "shared_context": self.shared_context,
        }
        if self.plan is not None:
            context["plan"] = asdict(self.plan)
        # Keep output summaries small to avoid prompt bloat.
        outputs: list[dict[str, Any]] = []
        for agent_id, result in self.agent_outputs.items():
            outputs.append(
                {
                    "agent_id": agent_id,
                    "agent_type": result.agent_type,
                    "status": result.status,
                    "confidence": result.confidence,
                    "tool": result.tool_name,
                    "summary": result.output[:500],
                }
            )
        context["agent_outputs"] = outputs
        return context

    def persist(self) -> None:
        payload = {
            "goal": self.goal,
            "plan": asdict(self.plan) if self.plan else None,
            "agent_outputs": {
                agent_id: asdict(result) for agent_id, result in self.agent_outputs.items()
            },
            "shared_context": self.shared_context,
        }
        blob = json.dumps(payload, separators=(",", ":"))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO swarm_memory (session_id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (self.session_id, blob, time.time()),
            )
            conn.commit()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS swarm_memory (
                    session_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()
