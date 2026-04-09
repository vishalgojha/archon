"""Natural Language Swarm Debugging - explain swarm failures in plain English."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentSnapshot:
    """State of an agent at a point in time."""

    agent_id: str
    agent_type: str
    status: str
    skill: str | None
    action: str
    started_at: float
    completed_at: float | None = None


@dataclass
class ForensicReport:
    """Complete forensic reconstruction of a swarm failure."""

    task_id: str
    goal: str
    failed_at: float
    error: str
    agent_chain: list[AgentSnapshot] = field(default_factory=list)
    dna_lineage: list[dict[str, Any]] = field(default_factory=list)
    skill_performance: dict[str, float] = field(default_factory=dict)


class NaturalLanguageDebugger:
    """Debugs swarm failures in plain English."""

    def __init__(
        self,
        genealogy_db: str | Path = "archon_genealogy.sqlite3",
        evolution_db: str | Path = "archon_swarm.sqlite3",
    ):
        self.genealogy_db = genealogy_db
        self.evolution_db = evolution_db

    def ask(self, question: str) -> str:
        """Answer natural language questions about swarm failures."""
        question = question.lower()
        
        if "why" in question and "fail" in question:
            return self._explain_last_failure()
        
        if "what happened" in question or "what went wrong" in question:
            return self._explain_last_failure()
        
        if "when" in question and "3pm" in question or "at" in question:
            time_match = re.search(r"(at |@)(\d{1,2}:\d{2})", question)
            if time_match:
                return self._explain_failure_at(time_match.group(2))
        
        if "which agent" in question or "who" in question:
            return self._blame_agent()
        
        if "how" in question and ("fix" in question or "solve" in question):
            return self._suggest_fix()
        
        if "lineage" in question or "ancestor" in question:
            return self._explain_lineage()
        
        return "I can answer: 'why did it fail', 'what happened at 3pm', 'which agent caused it', 'how to fix', or 'show lineage'"

    def _explain_last_failure(self) -> str:
        """Explain the most recent failure."""
        conn = sqlite3.connect(self.evolution_db)
        
        cursor = conn.execute(
            """SELECT task_id, goal, error FROM task_snapshots 
               ORDER BY failed_at DESC LIMIT 1"""
        )
        row = cursor.fetchone()
        
        if not row:
            return "No recent failures found."
        
        task_id, goal, error = row
        
        cursor = conn.execute(
            "SELECT agent_id, agent_type, action FROM task_agents WHERE task_id = ? ORDER BY started_at",
            (task_id,)
        )
        agents = cursor.fetchall()
        conn.close()
        
        lines = [
            f"📋 Task: {goal}",
            f"❌ Failed: {error}",
            "",
            "Agent Chain:"
        ]
        
        for agent in agents:
            lines.append(f"  → {agent[1]} ({agent[2]})")
        
        if not agents:
            lines.append("  (No agents were spawned)")
        
        return "\n".join(lines)

    def _explain_failure_at(self, time_str: str) -> str:
        """Explain failures at a specific time."""
        hour, minute = map(int, time_str.split(':'))
        target_ts = hour * 3600 + minute * 60
        
        conn = sqlite3.connect(self.evolution_db)
        
        cursor = conn.execute(
            """SELECT task_id, goal, error, failed_at FROM task_snapshots 
               ORDER BY ABS(failed_at - ?)""",
            (target_ts,)
        )
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return f"No task found near {time_str}"
        
        task_id, goal, error, _ = row
        conn.close()
        
        return f"At {time_str}, task '{goal}' failed with: {error}"

    def _blame_agent(self) -> str:
        """Identify which agent likely caused the failure."""
        conn = sqlite3.connect(self.evolution_db)
        
        cursor = conn.execute(
            """SELECT task_id, goal FROM task_snapshots 
               ORDER BY failed_at DESC LIMIT 1"""
        )
        row = cursor.fetchone()
        
        if not row:
            return "No failures to analyze."
        
        task_id, goal = row
        
        cursor = conn.execute(
            """SELECT agent_type, action, status FROM task_agents 
               WHERE task_id = ? ORDER BY started_at""",
            (task_id,)
        )
        agents = cursor.fetchall()
        
        cursor = conn.execute(
            "SELECT skill_name, success_count, failure_count FROM skill_performance ORDER BY failure_count DESC LIMIT 3"
        )
        worst_skills = cursor.fetchall()
        
        conn.close()
        
        lines = ["🔍 Most likely culprits:"]
        
        for agent in agents:
            if agent[2] == "failed":
                lines.append(f"  • {agent[0]} failed during: {agent[1]}")
        
        if worst_skills:
            lines.append("")
            lines.append("Underperforming skills:")
            for skill, success, failure in worst_skills:
                lines.append(f"  • {skill}: {failure} failures, {success} successes")
        
        return "\n".join(lines)

    def _suggest_fix(self) -> str:
        """Suggest how to fix the failure."""
        conn = sqlite3.connect(self.evolution_db)
        
        cursor = conn.execute(
            """SELECT task_id, goal FROM task_snapshots 
               ORDER BY failed_at DESC LIMIT 1"""
        )
        row = cursor.fetchone()
        
        if not row:
            return "No failures to fix."
        
        task_id, goal = row
        
        cursor = conn.execute(
            """SELECT task_id, goal, status FROM task_history 
               WHERE goal LIKE ? AND status = 'completed'
               ORDER BY completed_at DESC LIMIT 3""",
            (f"%{goal}%",)
        )
        similar = cursor.fetchall()
        conn.close()
        
        lines = ["💡 Suggestions:"]
        
        if similar:
            lines.append(f"  • Found {len(similar)} similar tasks that succeeded")
            lines.append("  • Try reusing their agent configuration")
        
        lines.append("  • Enable more verbose logging")
        lines.append("  • Add a ValidatorAgent before the Synthesizer")
        
        return "\n".join(lines)

    def _explain_lineage(self) -> str:
        """Show agent lineage for recent failure."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.genealogy_db)
            cursor = conn.execute(
                "SELECT dna_id, parent_id, goal_type, success_rate FROM agent_dna ORDER BY created_at DESC LIMIT 5"
            )
            rows = cursor.fetchall()
            conn.close()
            
            if not rows:
                return "No lineage data available."
            
            lines = ["🧬 Agent Lineage (recent):"]
            for row in rows:
                parent = f"child of {row[1][:12]}" if row[1] else "founder"
                lines.append(f"  • {row[0][:12]}... ({row[2]}) {parent} - {row[3]:.0%} success")
            
            return "\n".join(lines)
        except Exception:
            return "Lineage database not initialized."

    def get_forensic_report(self, task_id: str) -> ForensicReport:
        """Generate complete forensic report for a task."""
        conn = sqlite3.connect(self.evolution_db)
        
        cursor = conn.execute(
            "SELECT task_id, goal, failed_at, error, agent_chain FROM task_snapshots WHERE task_id = ?",
            (task_id,)
        )
        snapshot_row = cursor.fetchone()
        
        if not snapshot_row:
            cursor = conn.execute(
                "SELECT task_id, goal, mode, status, completed_at, result FROM task_history WHERE task_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                return ForensicReport(
                    task_id=task_id,
                    goal="",
                    failed_at=0,
                    error="Task not found"
                )
            
            return ForensicReport(
                task_id=row[0],
                goal=row[1],
                failed_at=row[4] or 0,
                error=row[3]
            )
        
        agent_chain = json.loads(snapshot_row[4]) if snapshot_row[4] else []
        
        cursor = conn.execute(
            "SELECT skill_name, success_count, failure_count FROM skill_performance"
        )
        skills = cursor.fetchall()
        
        conn.close()
        
        skill_performance = {
            s[0]: s[1] / (s[1] + s[2]) if (s[1] + s[2]) > 0 else 0
            for s in skills
        }
        
        return ForensicReport(
            task_id=snapshot_row[0],
            goal=snapshot_row[1],
            failed_at=snapshot_row[2],
            error=snapshot_row[3],
            agent_chain=[
                AgentSnapshot(
                    agent_id=a.get("agent_id", ""),
                    agent_type=a.get("agent_type", ""),
                    status=a.get("status", ""),
                    skill=a.get("skill"),
                    action=a.get("action", ""),
                    started_at=a.get("started_at", 0),
                    completed_at=a.get("completed_at")
                ) for a in agent_chain
            ],
            skill_performance=skill_performance
        )

    def explain_in_plain_english(self, task_id: str) -> str:
        """Generate human-readable explanation."""
        report = self.get_forensic_report(task_id)
        
        lines = [
            f"Task: {report.goal}",
            f"Status: {'❌ FAILED' if report.error else '✅ Completed'}",
            ""
        ]
        
        if report.error:
            lines.append(f"Error: {report.error}")
            lines.append("")
        
        if report.agent_chain:
            lines.append("What happened:")
            for i, agent in enumerate(report.agent_chain):
                status_icon = "✅" if agent.status == "completed" else "⏳"
                lines.append(f"  {i+1}. {status_icon} {agent.agent_type} -> {agent.action}")
        
        if report.skill_performance:
            worst = sorted(report.skill_performance.items(), key=lambda x: x[1])[:3]
            lines.append("")
            lines.append("Struggling skills:")
            for skill, rate in worst:
                lines.append(f"  • {skill}: {rate:.0%} success rate")
        
        return "\n".join(lines)
