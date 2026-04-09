"""Agent Genealogy - tracks parent-child lineage and passes learned DNA to children."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentDNA:
    """Genetic code passed from parent to child agents."""

    dna_id: str
    parent_id: str | None
    goal_type: str
    successful_patterns: list[str] = field(default_factory=list)
    failed_patterns: list[str] = field(default_factory=list)
    learned_insights: list[str] = field(default_factory=list)
    success_rate: float = 0.0
    task_count: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class AgentLineage:
    """Complete lineage tree for an agent."""

    agent_id: str
    dna: AgentDNA
    ancestors: list[AgentDNA] = field(default_factory=list)
    children: list[str] = field(default_factory=list)


class AgentGenealogy:
    """Tracks agent lineage and propagates learned DNA through generations."""

    def __init__(self, db_path: str | Path = "archon_genealogy.sqlite3"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_dna (
                dna_id TEXT PRIMARY KEY,
                parent_id TEXT,
                goal_type TEXT NOT NULL,
                successful_patterns TEXT,
                failed_patterns TEXT,
                learned_insights TEXT,
                success_rate REAL DEFAULT 0.0,
                task_count INTEGER DEFAULT 0,
                created_at REAL,
                FOREIGN KEY (parent_id) REFERENCES agent_dna(dna_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_lineage (
                agent_id TEXT PRIMARY KEY,
                dna_id TEXT NOT NULL,
                created_at REAL,
                FOREIGN KEY (dna_id) REFERENCES agent_dna(dna_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS genealogy_events (
                event_id TEXT PRIMARY KEY,
                agent_id TEXT,
                event_type TEXT,
                details TEXT,
                timestamp REAL
            )
        """)
        conn.commit()
        conn.close()

    def spawn_agent(
        self,
        goal: str,
        parent_id: str | None = None,
        inherited_patterns: list[str] | None = None,
    ) -> tuple[str, str]:
        """Spawn a new agent with lineage tracking. Returns (agent_id, dna_id)."""
        agent_id = f"agent_{uuid.uuid4().hex[:12]}"
        dna_id = f"dna_{uuid.uuid4().hex[:12]}"
        
        goal_type = goal.strip().split()[0].lower() if goal else "general"
        
        successful = []
        if parent_id:
            parent_dna = self.get_dna_by_agent_id(parent_id)
            if parent_dna:
                successful = list(parent_dna.successful_patterns)
                if inherited_patterns:
                    successful.extend(inherited_patterns)
        
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO agent_dna 
               (dna_id, parent_id, goal_type, successful_patterns, failed_patterns, 
                learned_insights, success_rate, task_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (dna_id, parent_id, goal_type, json.dumps(successful), json.dumps([]),
             json.dumps([]), 0.0, 0, time.time())
        )
        conn.execute(
            """INSERT INTO agent_lineage (agent_id, dna_id, created_at)
               VALUES (?, ?, ?)""",
            (agent_id, dna_id, time.time())
        )
        conn.execute(
            """INSERT INTO genealogy_events (event_id, agent_id, event_type, details, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (f"evt_{uuid.uuid4().hex[:8]}", agent_id, "spawned", json.dumps({"parent_id": parent_id}), time.time())
        )
        conn.commit()
        conn.close()
        
        return agent_id, dna_id

    def record_success(self, agent_id: str, pattern: str, insight: str | None = None) -> None:
        """Record successful execution - propagates to DNA."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT dna_id FROM agent_lineage WHERE agent_id = ?", (agent_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return
        
        dna_id = row[0]
        
        cursor = conn.execute(
            "SELECT successful_patterns, learned_insights, task_count FROM agent_dna WHERE dna_id = ?",
            (dna_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return
        
        successful = json.loads(row[0])
        insights = json.loads(row[1])
        count = row[2]
        
        if pattern not in successful:
            successful.append(pattern)
        if insight and insight not in insights:
            insights.append(Insight)
        
        new_rate = (count + 1) / (count + 1) if count > 0 else 1.0
        
        conn.execute(
            """UPDATE agent_dna SET successful_patterns = ?, learned_insights = ?, 
               task_count = ?, success_rate = ? WHERE dna_id = ?""",
            (json.dumps(successful), json.dumps(insights), count + 1, new_rate, dna_id)
        )
        conn.execute(
            """INSERT INTO genealogy_events (event_id, agent_id, event_type, details, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (f"evt_{uuid.uuid4().hex[:8]}", agent_id, "success", json.dumps({"pattern": pattern}), time.time())
        )
        conn.commit()
        conn.close()

    def record_failure(self, agent_id: str, failed_pattern: str, reason: str) -> None:
        """Record failed execution."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT dna_id FROM agent_lineage WHERE agent_id = ?", (agent_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return
        
        dna_id = row[0]
        
        cursor = conn.execute(
            "SELECT failed_patterns, task_count FROM agent_dna WHERE dna_id = ?",
            (dna_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return
        
        failed = json.loads(row[0])
        count = row[1]
        
        if failed_pattern not in failed:
            failed.append(failed_pattern)
        
        new_rate = 0.0 if count == 0 else (count - 1) / count
        
        conn.execute(
            """UPDATE agent_dna SET failed_patterns = ?, task_count = ?, 
               success_rate = ? WHERE dna_id = ?""",
            (json.dumps(failed), count + 1, new_rate, dna_id)
        )
        conn.execute(
            """INSERT INTO genealogy_events (event_id, agent_id, event_type, details, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (f"evt_{uuid.uuid4().hex[:8]}", agent_id, "failure", json.dumps({"pattern": failed_pattern, "reason": reason}), time.time())
        )
        conn.commit()
        conn.close()

    def get_dna_by_agent_id(self, agent_id: str) -> AgentDNA | None:
        """Get DNA for an agent."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """SELECT d.dna_id, d.parent_id, d.goal_type, d.successful_patterns, 
                      d.failed_patterns, d.learned_insights, d.success_rate, d.task_count, d.created_at
               FROM agent_dna d
               JOIN agent_lineage l ON d.dna_id = l.dna_id
               WHERE l.agent_id = ?""",
            (agent_id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return AgentDNA(
            dna_id=row[0],
            parent_id=row[1],
            goal_type=row[2],
            successful_patterns=json.loads(row[3]),
            failed_patterns=json.loads(row[4]),
            learned_insights=json.loads(row[5]),
            success_rate=row[6],
            task_count=row[7],
            created_at=row[8]
        )

    def get_lineage(self, agent_id: str) -> list[AgentDNA]:
        """Trace full ancestry of an agent."""
        lineage = []
        current_id = agent_id
        
        conn = sqlite3.connect(self.db_path)
        while True:
            cursor = conn.execute(
                """SELECT d.dna_id, d.parent_id, d.goal_type, d.successful_patterns,
                          d.failed_patterns, d.learned_insights, d.success_rate, d.task_count, d.created_at
                   FROM agent_dna d
                   JOIN agent_lineage l ON d.dna_id = l.dna_id
                   WHERE l.agent_id = ?""",
                (current_id,)
            )
            row = cursor.fetchone()
            if not row:
                break
            
            lineage.append(AgentDNA(
                dna_id=row[0],
                parent_id=row[1],
                goal_type=row[2],
                successful_patterns=json.loads(row[3]),
                failed_patterns=json.loads(row[4]),
                learned_insights=json.loads(row[5]),
                success_rate=row[6],
                task_count=row[7],
                created_at=row[8]
            ))
            
            if row[1]:
                cursor = conn.execute(
                    "SELECT agent_id FROM agent_lineage WHERE dna_id = ?", (row[1],)
                )
                parent_row = cursor.fetchone()
                current_id = parent_row[0] if parent_row else None
            else:
                break
        
        conn.close()
        return lineage

    def get_best_ancestor_patterns(self, goal_type: str, limit: int = 5) -> list[str]:
        """Get most successful patterns from ancestors for a goal type."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """SELECT d.successful_patterns, d.success_rate 
               FROM agent_dna d
               WHERE d.goal_type = ? AND d.success_rate > 0.5
               ORDER BY d.success_rate DESC
               LIMIT ?""",
            (goal_type, limit)
        )
        rows = cursor.fetchall()
        conn.close()
        
        patterns = []
        for row in rows:
            patterns.extend(json.loads(row[0]))
        
        return patterns[:limit]

    def explain_decision(self, agent_id: str) -> str:
        """Explain why an agent made a decision based on lineage."""
        lineage = self.get_lineage(agent_id)
        
        if not lineage:
            return f"Agent {agent_id}: No lineage - spawned fresh"
        
        lines = [f"Agent {agent_id} lineage:"]
        for i, dna in enumerate(lineage):
            lines.append(f"  Gen {i}: {dna.goal_type} (rate: {dna.success_rate:.0%}, {dna.task_count} tasks)")
            if dna.successful_patterns:
                lines.append(f"    ✓ Learned: {', '.join(dna.successful_patterns[-3:])}")
            if dna.failed_patterns:
                lines.append(f"    ✗ Avoided: {', '.join(dna.failed_patterns[-3:])}")
        
        return "\n".join(lines)

    def find_similar_successful_ancestor(self, goal: str, failed_agent_id: str) -> str | None:
        """Find ancestor that succeeded on similar goal - for resurrection."""
        goal_type = goal.strip().split()[0].lower() if goal else "general"
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """SELECT l.agent_id, d.success_rate 
               FROM agent_dna d
               JOIN agent_lineage l ON d.dna_id = l.dna_id
               WHERE d.goal_type = ? AND d.success_rate > 0.7
               ORDER BY d.success_rate DESC
               LIMIT 1""",
            (goal_type,)
        )
        row = cursor.fetchone()
        conn.close()
        
        return row[0] if row else None
