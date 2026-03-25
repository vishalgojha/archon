"""Evolution engine backing the self-evolving swarm."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from archon.memory.embedder import Embedder
from archon.swarm.types import AgentResult, AgentSpec, SwarmResult


class EvolutionEngine:
    """Persists swarm outcomes and guides future spawning decisions."""

    def __init__(self, *, db_path: str = "archon_swarm.sqlite3") -> None:
        self.db_path = db_path
        self._enable_embeddings = str(os.getenv("ARCHON_SWARM_EMBEDDINGS", "off")).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._embedder: Embedder | None = None
        self._apply_migrations()
        if self._enable_embeddings:
            try:
                self._embedder = Embedder(db_path=db_path)
            except Exception:
                self._embedder = None

    async def record(self, session_id: str, result: SwarmResult) -> None:
        """Record swarm outcomes and update skill performance."""

        now = time.time()
        manifest_json = json.dumps(
            [asdict(spec) for spec in result.agent_manifest], separators=(",", ":")
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO task_history (task_id, goal, agent_manifest_json, result_text, success,
                                          duration_seconds, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.task_id,
                    result.goal,
                    manifest_json,
                    result.final_answer,
                    1 if result.success else 0,
                    float(result.duration_seconds),
                    now,
                ),
            )
            conn.commit()

        self._update_skill_performance(result.agent_results, now)
        self._update_spawn_pattern(result.goal, result.agent_manifest, result.success, now)

        if self._enable_embeddings and self._embedder is not None:
            embedding = self._embedder.embed(result.goal)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO goal_embeddings (task_id, goal, embedding_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        goal = excluded.goal,
                        embedding_json = excluded.embedding_json
                    """,
                    (
                        result.task_id,
                        result.goal,
                        json.dumps(embedding, separators=(",", ":")),
                    ),
                )
                conn.commit()

    def find_similar(self, goal: str, *, limit: int = 3) -> list[dict[str, Any]]:
        """Return similar past tasks using embeddings when available."""

        if not self._enable_embeddings or self._embedder is None:
            return []

        embedding = self._embedder.embed(goal)
        rows: list[tuple[str, str, str]] = []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT task_id, goal, embedding_json FROM goal_embeddings"
            ).fetchall()

        scored: list[tuple[float, dict[str, Any]]] = []
        for task_id, past_goal, vector_json in rows:
            try:
                vector = json.loads(vector_json)
            except json.JSONDecodeError:
                continue
            score = _cosine_similarity(embedding, vector)
            scored.append((score, {"task_id": task_id, "goal": past_goal, "score": score}))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[: max(1, int(limit))]]

    def get_best_spawn_pattern(self, goal_type: str) -> list[AgentSpec]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT pattern_json FROM spawn_patterns WHERE goal_type = ?",
                (goal_type,),
            ).fetchone()
        if row is None:
            return []
        try:
            raw = json.loads(str(row[0]))
        except json.JSONDecodeError:
            return []
        if not isinstance(raw, list):
            return []
        specs: list[AgentSpec] = []
        for item in raw:
            if isinstance(item, dict):
                specs.append(AgentSpec(**item))
        return specs

    def prune_underperforming_skills(self) -> list[str]:
        """Return skills below a 30% success rate."""
        threshold = float(os.getenv("ARCHON_SWARM_PRUNE_THRESHOLD", "0.3"))
        flagged: list[str] = []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT skill_name, success_count, failure_count FROM skill_performance"
            ).fetchall()
        for name, success_count, failure_count in rows:
            total = int(success_count) + int(failure_count)
            if total == 0:
                continue
            rate = float(success_count) / float(total)
            if rate < threshold:
                flagged.append(str(name))
        return flagged

    def _apply_migrations(self) -> None:
        migrations_dir = Path(__file__).with_suffix("").parent / "migrations"
        migrations = sorted(p for p in migrations_dir.glob("*.sql"))
        if not migrations:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS swarm_migrations (id TEXT PRIMARY KEY, applied_at REAL)"
            )
            applied = {row[0] for row in conn.execute("SELECT id FROM swarm_migrations").fetchall()}
            for migration in migrations:
                migration_id = migration.name
                if migration_id in applied:
                    continue
                sql = migration.read_text(encoding="utf-8")
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO swarm_migrations (id, applied_at) VALUES (?, ?)",
                    (migration_id, time.time()),
                )
            conn.commit()

    def _update_skill_performance(self, results: list[AgentResult], now: float) -> None:
        by_skill: dict[str, list[AgentResult]] = {}
        for result in results:
            if not result.tool_name:
                continue
            by_skill.setdefault(result.tool_name, []).append(result)

        with sqlite3.connect(self.db_path) as conn:
            for skill_name, skill_results in by_skill.items():
                success_count = sum(1 for r in skill_results if r.status == "DONE")
                failure_count = sum(1 for r in skill_results if r.status != "DONE")
                avg_confidence = sum(r.confidence for r in skill_results) / max(
                    len(skill_results), 1
                )
                existing = conn.execute(
                    "SELECT success_count, failure_count, avg_confidence FROM skill_performance WHERE skill_name = ?",
                    (skill_name,),
                ).fetchone()
                if existing:
                    prev_success, prev_failure, prev_avg = existing
                    total_prev = prev_success + prev_failure
                    total_new = total_prev + success_count + failure_count
                    if total_new > 0:
                        avg_confidence = (
                            (prev_avg * total_prev)
                            + (avg_confidence * (success_count + failure_count))
                        ) / total_new
                    success_count += int(prev_success)
                    failure_count += int(prev_failure)
                conn.execute(
                    """
                    INSERT INTO skill_performance (skill_name, success_count, failure_count, avg_confidence, last_used)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(skill_name) DO UPDATE SET
                        success_count = excluded.success_count,
                        failure_count = excluded.failure_count,
                        avg_confidence = excluded.avg_confidence,
                        last_used = excluded.last_used
                    """,
                    (skill_name, success_count, failure_count, float(avg_confidence), now),
                )
            conn.commit()

    def _update_spawn_pattern(
        self,
        goal: str,
        manifest: list[AgentSpec],
        success: bool,
        now: float,
    ) -> None:
        goal_type = _goal_type(goal)
        pattern_json = json.dumps([asdict(spec) for spec in manifest], separators=(",", ":"))
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT success_rate, sample_count FROM spawn_patterns WHERE goal_type = ?",
                (goal_type,),
            ).fetchone()
            if row:
                success_rate, sample_count = row
                sample_count = int(sample_count) + 1
                success_rate = (
                    (float(success_rate) * (sample_count - 1)) + (1.0 if success else 0.0)
                ) / float(sample_count)
            else:
                sample_count = 1
                success_rate = 1.0 if success else 0.0
            conn.execute(
                """
                INSERT INTO spawn_patterns (goal_type, pattern_json, success_rate, sample_count, last_used)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(goal_type) DO UPDATE SET
                    pattern_json = excluded.pattern_json,
                    success_rate = excluded.success_rate,
                    sample_count = excluded.sample_count,
                    last_used = excluded.last_used
                """,
                (goal_type, pattern_json, float(success_rate), int(sample_count), now),
            )
            conn.commit()


def _goal_type(goal: str) -> str:
    tokens = goal.strip().lower().split()
    if not tokens:
        return "general"
    return tokens[0]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
