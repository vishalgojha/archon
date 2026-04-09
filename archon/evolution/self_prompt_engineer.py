"""Self-Prompt Engineering - the swarm learns to improve its own prompts.

This is Archon's "mind" - the internal language it uses to think and instruct itself.
The swarm observes outcomes and iteratively rewrites its own prompts.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PromptGene:
    """A prompt variant with evolutionary tracking."""

    gene_id: str
    prompt_type: str
    content: str
    version: int
    parent_gene_id: str | None
    success_rate: float = 0.0
    total_uses: int = 0
    created_at: float = field(default_factory=time.time)
    last_used: float | None = None


@dataclass
class PromptEvolutionResult:
    """Result of evolving prompts."""

    original_gene: PromptGene
    improved_gene: PromptGene
    improvement_score: float
    rationale: str


class SelfPromptEngineer:
    """The swarm's cognitive evolution system - it learns to talk to itself better."""

    def __init__(self, db_path: str | Path = "archon_prompts.sqlite3"):
        self.db_path = db_path
        self._init_db()
        self._ensure_foundation_prompts()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prompt_genes (
                gene_id TEXT PRIMARY KEY,
                prompt_type TEXT NOT NULL,
                content TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                parent_gene_id TEXT,
                success_rate REAL DEFAULT 0.0,
                total_uses INTEGER DEFAULT 0,
                created_at REAL,
                last_used REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prompt_observations (
                obs_id TEXT PRIMARY KEY,
                gene_id TEXT,
                input_type TEXT,
                output_quality REAL,
                feedback TEXT,
                observed_at REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_prompts (
                prompt_id TEXT PRIMARY KEY,
                prompt_type TEXT NOT NULL,
                content TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                active_gene_id TEXT,
                updated_at REAL
            )
        """)
        conn.commit()
        conn.close()

    def _ensure_foundation_prompts(self) -> None:
        """Create foundation prompts if they don't exist."""
        foundation_prompts = {
            "system_instructions": """You are Archon, a self-evolving agentic swarm. 
You decompose goals, execute tasks in parallel, and synthesize results.
You have access to skills from a registry. You learn from every interaction.
Always aim for the highest confidence answer.""",
            
            "decomposer_instructions": """You are a Goal Decomposer.
Break down the user's goal into independent subtasks that can run in parallel.
Each subtask should be self-contained and produce a usable intermediate result.
Output a JSON list of subtasks with 'task_id', 'description', and 'dependencies'.""",
            
            "synthesizer_instructions": """You are a Synthesizer.
Combine multiple agent results into a coherent final answer.
Identify agreements, disagreements, and knowledge gaps.
Prioritize high-confidence information. Cite sources.""",
            
            "validator_instructions": """You are a Validator.
Check the synthesized answer for:
- Factual accuracy
- Logical consistency
- Completeness
- Confidence scoring
Output validation results and suggest improvements.""",
            
            "critic_instructions": """You are a Critic.
Identify weaknesses in the current answer.
Question assumptions and highlight uncertainty.
Suggest alternative approaches.""",
        }
        
        conn = sqlite3.connect(self.db_path)
        for prompt_type, content in foundation_prompts.items():
            cursor = conn.execute(
                "SELECT prompt_id FROM system_prompts WHERE prompt_type = ?",
                (prompt_type,)
            )
            if not cursor.fetchone():
                gene_id = f"gene_foundation_{prompt_type}"
                conn.execute(
                    """INSERT INTO prompt_genes 
                       (gene_id, prompt_type, content, version, created_at)
                       VALUES (?, ?, ?, 1, ?)""",
                    (gene_id, prompt_type, content, time.time())
                )
                conn.execute(
                    """INSERT INTO system_prompts 
                       (prompt_id, prompt_type, content, is_active, active_gene_id, updated_at)
                       VALUES (?, ?, ?, 1, ?, ?)""",
                    (f"sys_{prompt_type}", prompt_type, content, gene_id, time.time())
                )
        conn.commit()
        conn.close()

    def get_active_prompt(self, prompt_type: str) -> str:
        """Get the currently active prompt for a type."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT content FROM system_prompts WHERE prompt_type = ? AND is_active = 1",
            (prompt_type,)
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else ""

    def record_outcome(
        self,
        prompt_type: str,
        input_context: str,
        output_quality: float,
        feedback: str | None = None,
    ) -> None:
        """Record an outcome to learn from."""
        conn = sqlite3.connect(self.db_path)
        
        cursor = conn.execute(
            "SELECT active_gene_id FROM system_prompts WHERE prompt_type = ?",
            (prompt_type,)
        )
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return
        
        gene_id = row[0]
        
        obs_id = f"obs_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """INSERT INTO prompt_observations 
               (obs_id, gene_id, input_type, output_quality, feedback, observed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (obs_id, gene_id, input_context, output_quality, feedback, time.time())
        )
        
        cursor = conn.execute(
            "SELECT total_uses FROM prompt_genes WHERE gene_id = ?",
            (gene_id,)
        )
        row = cursor.fetchone()
        total_uses = (row[0] if row else 0) + 1
        
        cursor = conn.execute(
            """SELECT AVG(output_quality) FROM prompt_observations 
               WHERE gene_id = ?""",
            (gene_id,)
        )
        avg_quality = cursor.fetchone()[0] or 0.5
        
        conn.execute(
            """UPDATE prompt_genes SET 
               success_rate = ?, total_uses = ?, last_used = ?
               WHERE gene_id = ?""",
            (avg_quality, total_uses, time.time(), gene_id)
        )
        conn.commit()
        conn.close()

    def evolve_prompt(
        self,
        prompt_type: str,
        improvement_hint: str | None = None,
    ) -> PromptEvolutionResult:
        """Create an evolved variant of a prompt based on observations."""
        conn = sqlite3.connect(self.db_path)
        
        cursor = conn.execute(
            "SELECT gene_id, content, version FROM system_prompts WHERE prompt_type = ?",
            (prompt_type,)
        )
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            raise ValueError(f"No active prompt for type: {prompt_type}")
        
        current_gene_id, current_content, version = row
        
        cursor = conn.execute(
            """SELECT feedback, output_quality FROM prompt_observations 
               WHERE gene_id = ? AND feedback IS NOT NULL
               ORDER BY observed_at DESC LIMIT 10""",
            (current_gene_id,)
        )
        observations = cursor.fetchall()
        
        original_gene = PromptGene(
            gene_id=current_gene_id,
            prompt_type=prompt_type,
            content=current_content,
            version=version,
            parent_gene_id=None,
        )
        
        improved_content = self._apply_improvements(current_content, observations, improvement_hint)
        
        new_gene_id = f"gene_{prompt_type}_{int(time.time())}"
        
        cursor = conn.execute(
            """SELECT success_rate FROM prompt_genes WHERE gene_id = ?""",
            (current_gene_id,)
        )
        old_rate = cursor.fetchone()[0] if cursor.fetchone() else 0.5
        
        conn.execute(
            """INSERT INTO prompt_genes 
               (gene_id, prompt_type, content, version, parent_gene_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (new_gene_id, prompt_type, improved_content, version + 1, current_gene_id, time.time())
        )
        
        conn.execute(
            """UPDATE system_prompts SET 
               content = ?, active_gene_id = ?, updated_at = ?
               WHERE prompt_type = ?""",
            (improved_content, new_gene_id, time.time(), prompt_type)
        )
        
        conn.commit()
        conn.close()
        
        return PromptEvolutionResult(
            original_gene=original_gene,
            improved_gene=PromptGene(
                gene_id=new_gene_id,
                prompt_type=prompt_type,
                content=improved_content,
                version=version + 1,
                parent_gene_id=current_gene_id,
            ),
            improvement_score=old_rate * 0.1,
            rationale=f"Evolved from v{version} based on {len(observations)} observations"
        )

    def _apply_improvements(
        self,
        current_content: str,
        observations: list[tuple],
        hint: str | None,
    ) -> str:
        """Apply improvements to prompt based on feedback."""
        improvements = []
        
        for feedback, quality in observations:
            if quality < 0.5 and feedback:
                improvements.append(feedback)
        
        if not improvements and not hint:
            return current_content
        
        lines = current_content.split('\n')
        
        if improvements:
            critique_section = "\n".join(f"- {imp}" for imp in improvements[:3])
            lines.append(f"\n## Recent critiques to address:\n{critique_section}")
        
        if hint:
            lines.append(f"\n## Improvement hint:\n{hint}")
        
        return '\n'.join(lines)

    def get_prompt_lineage(self, prompt_type: str) -> list[PromptGene]:
        """Get the evolutionary history of a prompt."""
        conn = sqlite3.connect(self.db_path)
        
        cursor = conn.execute(
            "SELECT gene_id, prompt_type, content, version, parent_gene_id, success_rate, total_uses, created_at FROM prompt_genes WHERE prompt_type = ? ORDER BY version DESC",
            (prompt_type,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [
            PromptGene(
                gene_id=row[0],
                prompt_type=row[1],
                content=row[2],
                version=row[3],
                parent_gene_id=row[4],
                success_rate=row[5],
                total_uses=row[6],
                created_at=row[7],
            ) for row in rows
        ]

    def synthesize_best_practices(self, prompt_type: str) -> str:
        """Synthesize best practices from all successful prompt variants."""
        conn = sqlite3.connect(self.db_path)
        
        cursor = conn.execute(
            """SELECT content FROM prompt_genes 
               WHERE prompt_type = ? AND success_rate > 0.7
               ORDER BY success_rate DESC LIMIT 5""",
            (prompt_type,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return self.get_active_prompt(prompt_type)
        
        best_practices = []
        for row in rows:
            content = row[0]
            key_lines = [l for l in content.split('\n') if l.strip() and not l.strip().startswith('#')]
            best_practices.extend(key_lines[:3])
        
        return '\n'.join(best_practices[:10])

    def create_few_shot_example(
        self,
        prompt_type: str,
        input_example: str,
        output_example: str,
    ) -> None:
        """Add a few-shot learning example to a prompt."""
        conn = sqlite3.connect(self.db_path)
        
        cursor = conn.execute(
            "SELECT content FROM system_prompts WHERE prompt_type = ?",
            (prompt_type,)
        )
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return
        
        content = row[0]
        
        example_block = f"""
## Few-shot example:
Input: {input_example}
Output: {output_example}
"""
        
        new_content = content + example_block
        
        conn.execute(
            "UPDATE system_prompts SET content = ?, updated_at = ? WHERE prompt_type = ?",
            (new_content, time.time(), prompt_type)
        )
        conn.commit()
        conn.close()

    def get_cognitive_report(self) -> dict[str, Any]:
        """Get a report on the swarm's current cognitive state."""
        conn = sqlite3.connect(self.db_path)
        
        cursor = conn.execute(
            """SELECT prompt_type, COUNT(*), AVG(success_rate), SUM(total_uses)
               FROM prompt_genes GROUP BY prompt_type"""
        )
        rows = cursor.fetchall()
        
        cursor = conn.execute("SELECT COUNT(*) FROM prompt_observations")
        total_obs = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "prompt_types": [
                {
                    "type": row[0],
                    "variants": row[1],
                    "avg_success_rate": row[2] or 0,
                    "total_uses": row[3] or 0,
                } for row in rows
            ],
            "total_observations": total_obs,
            "cognitive_age": time.time() - 1700000000
        }
