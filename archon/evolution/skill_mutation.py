"""Skill Mutation - genetic algorithm for combining underperforming skills into hybrids."""

from __future__ import annotations

import random
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SkillDNA:
    """Genetic code of a skill."""

    skill_id: str
    name: str
    parent_skills: list[str] = field(default_factory=list)
    code_snippets: list[str] = field(default_factory=list)
    success_rate: float = 0.0
    test_results: list[dict[str, Any]] = field(default_factory=list)
    generation: int = 0


@dataclass
class HybridCandidate:
    """A new skill created by combining two parent skills."""

    hybrid_id: str
    parent_a: str
    parent_b: str
    code: str
    generation: int
    fitness_score: float = 0.0


class SkillMutation:
    """Genetic algorithm that mutates and hybridizes skills."""

    def __init__(self, registry_path: str | Path = "archon_skills.sqlite3"):
        self.registry_path = registry_path
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.registry_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_mutations (
                hybrid_id TEXT PRIMARY KEY,
                parent_a TEXT,
                parent_b TEXT,
                code TEXT,
                generation INTEGER,
                fitness_score REAL DEFAULT 0.0,
                status TEXT DEFAULT 'sandbox',
                created_at REAL,
                tested_at REAL
            )
        """)
        conn.commit()
        conn.close()

    def get_underperforming_skills(self, threshold: float = 0.4) -> list[str]:
        """Find skills with success rate below threshold."""
        conn = sqlite3.connect(self.registry_path)
        cursor = conn.execute(
            """SELECT skill_name FROM skill_performance 
               WHERE success_count + failure_count > 5 
               AND CAST(success_count AS REAL) / (success_count + failure_count) < ?""",
            (threshold,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]

    def _extract_code_snippets(self, skill_name: str) -> list[str]:
        """Extract usable code patterns from a skill."""
        conn = sqlite3.connect(self.registry_path)
        cursor = conn.execute(
            "SELECT code FROM skills WHERE name = ?", (skill_name,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return []
        
        code = row[0]
        snippets = []
        
        lines = code.split('\n')
        current_snippet = []
        
        for line in lines:
            if line.strip().startswith('def ') or line.strip().startswith('async def '):
                if current_snippet:
                    snippets.append('\n'.join(current_snippet))
                current_snippet = []
            current_snippet.append(line)
        
        if current_snippet:
            snippets.append('\n'.join(current_snippet))
        
        return snippets

    def hybridize(self, skill_a: str, skill_b: str) -> HybridCandidate:
        """Combine two skills into a new experimental hybrid."""
        snippets_a = self._extract_code_snippets(skill_a)
        snippets_b = self._extract_code_snippets(skill_b)
        
        hybrid_code_parts = []
        
        if snippets_a and snippets_b:
            hybrid_code_parts.append(random.choice(snippets_a[:2]))
            hybrid_code_parts.append("# === HYBRID MERGE ===")
            hybrid_code_parts.append(random.choice(snippets_b[:2]))
        elif snippets_a:
            hybrid_code_parts.extend(snippets_a[:3])
        elif snippets_b:
            hybrid_code_parts.extend(snippets_b[:3])
        
        hybrid_code = '\n\n'.join(hybrid_code_parts)
        
        hybrid_id = f"hybrid_{uuid.uuid4().hex[:12]}"
        
        conn = sqlite3.connect(self.registry_path)
        conn.execute(
            """INSERT INTO skill_mutations 
               (hybrid_id, parent_a, parent_b, code, generation, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (hybrid_id, skill_a, skill_b, hybrid_code, 0, "sandbox", time.time())
        )
        conn.commit()
        conn.close()
        
        return HybridCandidate(
            hybrid_id=hybrid_id,
            parent_a=skill_a,
            parent_b=skill_b,
            code=hybrid_code,
            generation=0
        )

    def mutate(self, skill_name: str, mutation_rate: float = 0.1) -> str | None:
        """Randomly mutate a skill's code."""
        snippets = self._extract_code_snippets(skill_name)
        if not snippets:
            return None
        
        mutated_snippets = []
        for snippet in snippets:
            lines = snippet.split('\n')
            mutated = []
            for line in lines:
                if random.random() < mutation_rate:
                    if 'def ' in line:
                        line = line.replace('def ', 'async def ')
                    elif 'async def ' in line:
                        line = line.replace('async def ', 'def ')
                mutated.append(line)
            mutated_snippets.append('\n'.join(mutated))
        
        return '\n\n'.join(mutated_snippets)

    def create_generation(self, max_hybrids: int = 3) -> list[HybridCandidate]:
        """Create a new generation of hybrid skills from underperformers."""
        underperformers = self.get_underperforming_skills()
        
        if len(underperformers) < 2:
            return []
        
        pairs = []
        for i in range(0, min(len(underperformers), max_hybrids * 2), 2):
            if i + 1 < len(underperformers):
                pairs.append((underperformers[i], underperformers[i + 1]))
        
        hybrids = []
        for skill_a, skill_b in pairs:
            hybrid = self.hybridize(skill_a, skill_b)
            hybrids.append(hybrid)
        
        return hybrids

    def evaluate_in_sandbox(
        self,
        hybrid_id: str,
        test_cases: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Test a hybrid skill in sandbox before promotion."""
        conn = sqlite3.connect(self.registry_path)
        cursor = conn.execute(
            "SELECT code FROM skill_mutations WHERE hybrid_id = ?", (hybrid_id,)
        )
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return {"error": "Hybrid not found"}
        
        code = row[0]
        
        passed = 0
        failed = 0
        results = []
        
        for test in test_cases:
            try:
                exec(code, {"input": test["input"]})
                passed += 1
                results.append({"test": test["name"], "status": "passed"})
            except Exception as e:
                failed += 1
                results.append({"test": test["name"], "status": "failed", "error": str(e)})
        
        fitness = passed / len(test_cases) if test_cases else 0.0
        
        conn.execute(
            """UPDATE skill_mutations SET fitness_score = ?, tested_at = ?, status = ?
               WHERE hybrid_id = ?""",
            (fitness, time.time(), "tested" if fitness > 0.7 else "rejected", hybrid_id)
        )
        conn.commit()
        conn.close()
        
        return {
            "hybrid_id": hybrid_id,
            "fitness": fitness,
            "passed": passed,
            "failed": failed,
            "results": results
        }

    def promote_to_registry(self, hybrid_id: str, new_name: str) -> bool:
        """Promote a successful hybrid to the skill registry."""
        conn = sqlite3.connect(self.registry_path)
        cursor = conn.execute(
            "SELECT code, parent_a, parent_b FROM skill_mutations WHERE hybrid_id = ?", (hybrid_id,)
        )
        row = cursor.fetchone()
        
        if not row or row[0] is None:
            conn.close()
            return False
        
        conn.execute(
            """INSERT OR REPLACE INTO skills (name, code, version, created_at)
               VALUES (?, ?, ?, ?)""",
            (new_name, row[0], 1, time.time())
        )
        
        conn.execute(
            """INSERT INTO skill_performance (skill_name, success_count, failure_count, avg_confidence, last_used)
               VALUES (?, ?, ?, ?, ?)""",
            (new_name, 1, 0, 1.0, time.time())
        )
        
        conn.commit()
        conn.close()
        
        return True

    def get_mutation_stats(self) -> dict[str, Any]:
        """Get statistics about mutations."""
        conn = sqlite3.connect(self.registry_path)
        
        cursor = conn.execute("SELECT COUNT(*) FROM skill_mutations")
        total = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT COUNT(*) FROM skill_mutations WHERE status = 'tested'")
        tested = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT COUNT(*) FROM skill_mutations WHERE fitness_score > 0.7")
        promoted = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT AVG(fitness_score) FROM skill_mutations WHERE status = 'tested'")
        avg_fitness = cursor.fetchone()[0] or 0.0
        
        conn.close()
        
        return {
            "total_mutations": total,
            "tested": tested,
            "promoted": promoted,
            "average_fitness": avg_fitness
        }
