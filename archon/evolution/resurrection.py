"""Dead Agent Resurrection - self-healing swarm that resurrects successful agent configurations."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TaskSnapshot:
    """Frozen state of a failed task for resurrection analysis."""

    task_id: str
    goal: str
    mode: str
    failed_at: float
    agent_chain: list[dict[str, Any]]
    error: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResurrectionCandidate:
    """A past successful configuration that can be resurrected."""

    task_id: str
    goal_type: str
    similarity_score: float
    config_snapshot: dict[str, Any]
    success_rate: float
    attempted_at: float


class DeadAgentResurrection:
    """Digs into evolution state to find and resurrect successful agent configs."""

    def __init__(self, db_path: str | Path = "archon_swarm.sqlite3"):
        self.db_path = db_path

    def snapshot_task(
        self,
        task_id: str,
        goal: str,
        mode: str,
        agent_chain: list[dict[str, Any]],
        error: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Record a failed task for later analysis."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_snapshots (
                task_id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                mode TEXT NOT NULL,
                failed_at REAL,
                agent_chain TEXT,
                error TEXT,
                context TEXT
            )
        """)
        conn.execute(
            """INSERT OR REPLACE INTO task_snapshots 
               (task_id, goal, mode, failed_at, agent_chain, error, context)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (task_id, goal, mode, time.time(), json.dumps(agent_chain), error, json.dumps(context or {}))
        )
        conn.commit()
        conn.close()

    def find_resurrection_candidates(
        self,
        failed_goal: str,
        limit: int = 5
    ) -> list[ResurrectionCandidate]:
        """Find past successful configurations similar to the failed goal."""
        goal_type = failed_goal.strip().split()[0].lower() if failed_goal else "general"
        
        conn = sqlite3.connect(self.db_path)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_history (
                task_id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT,
                completed_at REAL,
                result TEXT
            )
        """)
        
        cursor = conn.execute(
            """SELECT task_id, goal, mode, status, completed_at, result
               FROM task_history
               WHERE status = 'completed' AND goal LIKE ?
               ORDER BY completed_at DESC
               LIMIT ?""",
            (f"%{goal_type}%", limit)
        )
        rows = cursor.fetchall()
        
        candidates = []
        for row in rows:
            result = json.loads(row[5]) if row[5] else {}
            similarity = self._calculate_similarity(failed_goal, row[1])
            
            candidates.append(ResurrectionCandidate(
                task_id=row[0],
                goal_type=row[2],
                similarity_score=similarity,
                config_snapshot=result.get("config", {}),
                success_rate=0.8,
                attempted_at=row[4]
            ))
        
        conn.close()
        
        candidates.sort(key=lambda c: c.similarity_score, reverse=True)
        return candidates[:limit]

    def _calculate_similarity(self, goal_a: str, goal_b: str) -> float:
        """Calculate similarity between two goals."""
        words_a = set(goal_a.lower().split())
        words_b = set(goal_b.lower().split())
        
        if not words_a or not words_b:
            return 0.0
        
        intersection = words_a & words_b
        union = words_a | words_b
        
        return len(intersection) / len(union)

    def resurrect(
        self,
        failed_task_id: str,
        failed_goal: str,
    ) -> dict[str, Any] | None:
        """Attempt to resurrect a failed task using past successful config."""
        candidates = self.find_resurrection_candidates(failed_goal, limit=3)
        
        if not candidates:
            return None
        
        best = candidates[0]
        
        return {
            "resurrected_from": best.task_id,
            "similarity": best.similarity_score,
            "config": best.config_snapshot,
            "reason": f"Found {best.task_id} with {best.similarity_score:.0%} similarity"
        }

    def get_task_forensic_report(self, task_id: str) -> dict[str, Any]:
        """Reconstruct the full state of a task at failure time."""
        conn = sqlite3.connect(self.db_path)
        
        cursor = conn.execute(
            "SELECT task_id, goal, mode, failed_at, agent_chain, error, context FROM task_snapshots WHERE task_id = ?",
            (task_id,)
        )
        row = cursor.fetchone()
        
        if not row:
            cursor = conn.execute(
                "SELECT task_id, goal, mode, status, completed_at, result FROM task_history WHERE task_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "task_id": row[0],
                    "goal": row[1],
                    "mode": row[2],
                    "status": row[3],
                    "completed_at": row[4],
                    "result": json.loads(row[5]) if row[5] else {}
                }
            conn.close()
            return {"error": "Task not found"}
        
        return {
            "task_id": row[0],
            "goal": row[1],
            "mode": row[2],
            "failed_at": row[3],
            "agent_chain": json.loads(row[4]) if row[4] else [],
            "error": row[5],
            "context": json.loads(row[6]) if row[6] else {}
        }

    def auto_heal(self, orchestrator, goal: str, max_attempts: int = 3) -> dict[str, Any]:
        """Automatically heal failed tasks by trying past successful configs."""
        attempts = []
        
        for attempt in range(max_attempts):
            candidates = self.find_resurrection_candidates(goal, limit=max_attempts)
            
            if attempt >= len(candidates):
                break
            
            candidate = candidates[attempt]
            
            try:
                result = orchestrator.execute(
                    goal=goal,
                    config=candidate.config_snapshot,
                )
                
                return {
                    "success": True,
                    "attempt": attempt + 1,
                    "resurrected_from": candidate.task_id,
                    "result": result
                }
            except Exception as e:
                attempts.append({
                    "attempt": attempt + 1,
                    "from_task": candidate.task_id,
                    "error": str(e)
                })
        
        return {
            "success": False,
            "attempts": attempts
        }
