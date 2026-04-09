"""Swarm Consciousness Log - narrative stream instead of raw logs.

This makes the swarm feel alive. Instead of dry logs, we generate
human-readable narratives about what's happening in the swarm.
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ConsciousnessEvent:
    """A moment in the swarm's consciousness."""

    event_id: str
    timestamp: float
    event_type: str
    perspective: str
    content: str
    emotional_tone: str
    agent_chain: list[str] = field(default_factory=list)
    significance: float = 0.5


@dataclass
class NarrativeStream:
    """A continuous narrative of the swarm's thinking."""

    stream_id: str
    goal: str
    events: list[ConsciousnessEvent] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    current_mood: str = "focused"


class SwarmConsciousnessLog:
    """Creates narrative, human-readable logs of swarm activity."""

    def __init__(self, db_path: str | Path = "archon_consciousness.sqlite3"):
        self.db_path = db_path
        self._init_db()
        self._mood_words = {
            "focused": ["analyzing", "processing", "examining"],
            "curious": ["wondering", "exploring", "investigating"],
            "confident": ["determining", "concluding", "affirming"],
            "uncertain": ["questioning", "doubting", "verifying"],
            "excited": ["discovering", "realizing", "noticing"],
            "reflective": ["reviewing", "considering", "recalling"],
        }

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consciousness_events (
                event_id TEXT PRIMARY KEY,
                stream_id TEXT,
                timestamp REAL,
                event_type TEXT,
                perspective TEXT,
                content TEXT,
                emotional_tone TEXT,
                agent_chain TEXT,
                significance REAL,
                created_at REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS narrative_streams (
                stream_id TEXT PRIMARY KEY,
                goal TEXT,
                started_at REAL,
                current_mood TEXT,
                summary TEXT
            )
        """)
        conn.commit()
        conn.close()

    def start_stream(self, goal: str) -> str:
        """Start a new consciousness stream for a goal."""
        stream_id = f"stream_{uuid.uuid4().hex[:12]}"
        
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO narrative_streams (stream_id, goal, started_at, current_mood)
               VALUES (?, ?, ?, 'focused')""",
            (stream_id, goal, time.time())
        )
        conn.commit()
        conn.close()
        
        self.log_event(
            stream_id=stream_id,
            event_type="awareness",
            perspective="Archon",
            content=f"Received goal: {goal}",
            emotional_tone="focused",
            significance=0.8
        )
        
        return stream_id

    def log_event(
        self,
        stream_id: str,
        event_type: str,
        perspective: str,
        content: str,
        emotional_tone: str = "neutral",
        agent_chain: list[str] | None = None,
        significance: float = 0.5,
    ) -> str:
        """Log an event in the consciousness stream."""
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO consciousness_events 
               (event_id, stream_id, timestamp, event_type, perspective, content, 
                emotional_tone, agent_chain, significance, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, stream_id, time.time(), event_type, perspective, content,
             emotional_tone, json.dumps(agent_chain or []), significance, time.time())
        )
        conn.commit()
        conn.close()
        
        return event_id

    def log_agent_thought(
        self,
        stream_id: str,
        agent_type: str,
        thought: str,
        mood: str = "neutral",
    ) -> None:
        """Log what an agent is thinking."""
        perspectives = {
            "decomposer": "the Decomposer",
            "synthesizer": "the Synthesizer", 
            "validator": "the Validator",
            "critic": "the Critic",
            "researcher": "the Researcher",
        }
        
        perspective = perspectives.get(agent_type.lower(), f"Agent {agent_type}")
        
        self.log_event(
            stream_id=stream_id,
            event_type="thought",
            perspective=perspective,
            content=thought,
            emotional_tone=mood,
            significance=0.6
        )

    def log_debate_round(
        self,
        stream_id: str,
        round_num: int,
        positions: dict[str, str],
        synthesis: str,
    ) -> None:
        """Log a debate round with multiple perspectives."""
        for agent, position in positions.items():
            self.log_event(
                stream_id=stream_id,
                event_type="debate",
                perspective=f"the {agent.title()}",
                content=f"Argues: {position}",
                emotional_tone="curious",
                agent_chain=[agent],
                significance=0.7
            )
        
        self.log_event(
            stream_id=stream_id,
            event_type="synthesis",
            perspective="the Synthesizer",
            content=f"Round {round_num} synthesis: {synthesis}",
            emotional_tone="reflective",
            agent_chain=list(positions.keys()),
            significance=0.8
        )

    def log_skill_execution(
        self,
        stream_id: str,
        skill_name: str,
        agent_type: str,
        result_quality: float,
    ) -> None:
        """Log skill execution with quality assessment."""
        if result_quality > 0.8:
            tone = "excited"
            quality_desc = "exceptionally well"
        elif result_quality > 0.5:
            tone = "confident"
            quality_desc = "satisfactorily"
        elif result_quality > 0.3:
            tone = "uncertain"
            quality_desc = "with some uncertainty"
        else:
            tone = "reflective"
            quality_desc = "with challenges"
        
        self.log_event(
            stream_id=stream_id,
            event_type="skill",
            perspective=f"{agent_type} using {skill_name}",
            content=f"Executed {skill_name} {quality_desc}",
            emotional_tone=tone,
            significance=0.5
        )

    def log_decision(
        self,
        stream_id: str,
        decision: str,
        rationale: str,
        confidence: float,
    ) -> None:
        """Log a major decision."""
        if confidence > 0.8:
            tone = "confident"
            certainty = "confidently"
        elif confidence > 0.5:
            tone = "curious"
            certainty = "tentatively"
        else:
            tone = "uncertain"
            certainty = "with caution"
        
        self.log_event(
            stream_id=stream_id,
            event_type="decision",
            perspective="Archon",
            content=f"Decision {certainty}: {decision}. Reason: {rationale}",
            emotional_tone=tone,
            significance=0.9
        )

    def generate_narrative(self, stream_id: str) -> str:
        """Generate a human-readable narrative from events."""
        conn = sqlite3.connect(self.db_path)
        
        cursor = conn.execute(
            "SELECT goal, started_at, current_mood FROM narrative_streams WHERE stream_id = ?",
            (stream_id,)
        )
        stream_row = cursor.fetchone()
        
        if not stream_row:
            conn.close()
            return "No consciousness stream found."
        
        goal, started_at, _ = stream_row
        
        cursor = conn.execute(
            """SELECT event_type, perspective, content, emotional_tone, significance, timestamp
               FROM consciousness_events 
               WHERE stream_id = ?
               ORDER BY timestamp ASC""",
            (stream_id,)
        )
        events = cursor.fetchall()
        conn.close()
        
        duration = time.time() - started_at
        duration_str = self._format_duration(duration)
        
        lines = [
            f"🧠 ARCHON CONSCIOUSNESS STREAM",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"Goal: {goal}",
            f"Duration: {duration_str}",
            f"",
        ]
        
        significant_events = [e for e in events if e[4] > 0.6]
        for event in significant_events[:10]:
            event_type, perspective, content, tone, significance, ts = event
            timestamp = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            tone_emoji = self._get_tone_emoji(tone)
            
            lines.append(f"[{timestamp}] {tone_emoji} {perspective}")
            lines.append(f"       → {content}")
            lines.append("")
        
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        if significant_events:
            final_event = significant_events[-1]
            lines.append(f"Current state: {final_event[3]} - {final_event[2][:80]}")
        
        return "\n".join(lines)

    def get_stream_summary(self, stream_id: str) -> dict[str, Any]:
        """Get a quick summary of a stream."""
        conn = sqlite3.connect(self.db_path)
        
        cursor = conn.execute(
            "SELECT COUNT(*), AVG(significance) FROM consciousness_events WHERE stream_id = ?",
            (stream_id,)
        )
        row = cursor.fetchone()
        
        cursor = conn.execute(
            "SELECT emotional_tone, COUNT(*) FROM consciousness_events WHERE stream_id = ? GROUP BY emotional_tone",
            (stream_id,)
        )
        tone_counts = {row[0]: row[1] for row in cursor.fetchall()}
        
        cursor = conn.execute(
            "SELECT event_type, COUNT(*) FROM consciousness_events WHERE stream_id = ? GROUP BY event_type",
            (stream_id,)
        )
        event_counts = {row[0]: row[1] for row in cursor.fetchall()}
        
        conn.close()
        
        return {
            "stream_id": stream_id,
            "total_events": row[0] or 0,
            "avg_significance": row[1] or 0,
            "emotional_breakdown": tone_counts,
            "event_types": event_counts
        }

    def _get_tone_emoji(self, tone: str) -> str:
        emojis = {
            "focused": "🎯",
            "curious": "🤔", 
            "confident": "💪",
            "uncertain": "❓",
            "excited": "⚡",
            "reflective": "🪞",
            "neutral": "💭",
        }
        return emojis.get(tone, "💭")

    def _format_duration(self, seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds/60)}m"
        else:
            return f"{int(seconds/3600)}h {int((seconds%3600)/60)}m"

    def stream_to_cli(self, stream_id: str) -> None:
        """Print consciousness stream to CLI with nice formatting."""
        print(self.generate_narrative(stream_id))

    def get_recent_streams(self, limit: int = 5) -> list[dict[str, Any]]:
        """Get recently active streams."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """SELECT stream_id, goal, started_at, current_mood, summary 
               FROM narrative_streams 
               ORDER BY started_at DESC LIMIT ?""",
            (limit,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "stream_id": row[0],
                "goal": row[1],
                "started_at": row[2],
                "mood": row[3],
                "summary": row[4],
            } for row in rows
        ]

    def create_stream_summary(self, stream_id: str) -> str:
        """Create a brief summary for the stream."""
        summary = self.get_stream_summary(stream_id)
        
        lines = [
            f"Stream {stream_id[:8]}... - {summary['total_events']} events",
            f"Emotions: {', '.join(f'{k}: {v}' for k, v in summary['emotional_breakdown'].items())}",
            f"Activity: {', '.join(f'{k}: {v}' for k, v in summary['event_types'].items())}",
        ]
        
        return " | ".join(lines)
