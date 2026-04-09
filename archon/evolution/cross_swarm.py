"""Cross-Swarm Memory - shared read-only skill registry between Archon instances."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SharedSkill:
    """A skill shared across swarms."""

    skill_id: str
    name: str
    domain: str
    code: str
    success_rate: float
    cross_domain_score: float = 0.0
    last_synced: float = field(default_factory=time.time)


@dataclass
class DomainProposal:
    """A skill proposed from another domain."""

    skill_name: str
    source_domain: str
    target_domain: str
    relevance_score: float
    proposed_at: float


class CrossSwarmMemory:
    """Enables multiple Archon instances to share skills and learn cross-domain."""

    def __init__(self, shared_db_path: str | Path = "archon_cross_swarm.sqlite3"):
        self.shared_db_path = shared_db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.shared_db_path)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shared_skills (
                skill_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                domain TEXT NOT NULL,
                code TEXT,
                success_rate REAL DEFAULT 0.0,
                cross_domain_score REAL DEFAULT 0.0,
                last_synced REAL
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS swarm_domains (
                domain TEXT PRIMARY KEY,
                instance_id TEXT,
                last_seen REAL
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cross_domain_proposals (
                proposal_id TEXT PRIMARY KEY,
                skill_name TEXT,
                source_domain TEXT,
                target_domain TEXT,
                relevance_score REAL,
                status TEXT DEFAULT 'pending',
                proposed_at REAL
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS domain_skill_matrix (
                domain TEXT,
                skill_name TEXT,
                usage_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                PRIMARY KEY (domain, skill_name)
            )
        """)
        
        conn.commit()
        conn.close()

    def register_swarm(self, domain: str, instance_id: str) -> None:
        """Register a new Archon instance/domain."""
        conn = sqlite3.connect(self.shared_db_path)
        conn.execute(
            """INSERT OR REPLACE INTO swarm_domains (domain, instance_id, last_seen)
               VALUES (?, ?, ?)""",
            (domain, instance_id, time.time())
        )
        conn.commit()
        conn.close()

    def publish_skill(
        self,
        domain: str,
        name: str,
        code: str,
        success_rate: float,
    ) -> str:
        """Publish a skill to the shared registry."""
        skill_id = f"shared_{domain}_{name}_{int(time.time())}"
        
        conn = sqlite3.connect(self.shared_db_path)
        conn.execute(
            """INSERT OR REPLACE INTO shared_skills 
               (skill_id, name, domain, code, success_rate, last_synced)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (skill_id, name, domain, code, success_rate, time.time())
        )
        
        conn.execute(
            """INSERT OR REPLACE INTO domain_skill_matrix (domain, skill_name, usage_count, success_count)
               VALUES (?, ?, 1, ?)""",
            (domain, name, 1 if success_rate > 0.5 else 0)
        )
        conn.commit()
        conn.close()
        
        return skill_id

    def get_skills_for_domain(
        self,
        target_domain: str,
        min_relevance: float = 0.3,
    ) -> list[SharedSkill]:
        """Get skills that might work for a target domain."""
        conn = sqlite3.connect(self.shared_db_path)
        
        cursor = conn.execute(
            """SELECT skill_id, name, domain, code, success_rate, cross_domain_score, last_synced
               FROM shared_skills
               WHERE domain != ? AND cross_domain_score > ?
               ORDER BY cross_domain_score DESC
               LIMIT 20""",
            (target_domain, min_relevance)
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [
            SharedSkill(
                skill_id=row[0],
                name=row[1],
                domain=row[2],
                code=row[3],
                success_rate=row[4],
                cross_domain_score=row[5],
                last_synced=row[6]
            ) for row in rows
        ]

    def record_skill_usage(
        self,
        domain: str,
        skill_name: str,
        success: bool,
    ) -> None:
        """Record when a skill is used to build cross-domain relevance."""
        conn = sqlite3.connect(self.shared_db_path)
        conn.execute(
            """INSERT OR REPLACE INTO domain_skill_matrix (domain, skill_name, usage_count, success_count)
               VALUES (?, ?, 
                       COALESCE((SELECT usage_count FROM domain_skill_matrix WHERE domain = ? AND skill_name = ?), 0) + 1,
                       COALESCE((SELECT success_count FROM domain_skill_matrix WHERE domain = ? AND skill_name = ?), 0) + ?)""",
            (domain, skill_name, domain, skill_name, domain, skill_name, 1 if success else 0)
        )
        conn.commit()
        conn.close()
        self._recalculate_cross_domain_scores(domain)

    def _recalculate_cross_domain_scores(self, domain: str) -> None:
        """Recalculate cross-domain relevance scores."""
        conn = sqlite3.connect(self.shared_db_path)
        
        cursor = conn.execute(
            "SELECT skill_name, usage_count, success_count FROM domain_skill_matrix WHERE domain = ?",
            (domain,)
        )
        rows = cursor.fetchall()
        
        for skill_name, usage, success in rows:
            rate = success / usage if usage > 0 else 0.0
            
            cursor = conn.execute(
                "SELECT COUNT(*) FROM domain_skill_matrix WHERE skill_name = ? AND domain != ?",
                (skill_name, domain)
            )
            other_domains = cursor.fetchone()[0]
            
            cross_score = rate * min(other_domains / 3, 1.0)
            
            conn.execute(
                """UPDATE shared_skills SET cross_domain_score = ?
                   WHERE name = ? AND domain != ?""",
                (cross_score, skill_name, domain)
            )
        
        conn.commit()
        conn.close()

    def propose_cross_domain_skills(
        self,
        target_domain: str,
        source_domain: str,
    ) -> list[DomainProposal]:
        """Propose skills from source domain that might work in target."""
        conn = sqlite3.connect(self.shared_db_path)
        
        cursor = conn.execute(
            """SELECT s.name, s.cross_domain_score
               FROM shared_skills s
               WHERE s.domain = ? AND s.cross_domain_score > 0.3
               ORDER BY s.cross_domain_score DESC
               LIMIT 10""",
            (source_domain,)
        )
        rows = cursor.fetchall()
        
        proposals = []
        for name, score in rows:
            proposal_id = f"proposal_{int(time.time())}_{name}"
            conn.execute(
                """INSERT INTO cross_domain_proposals 
                   (proposal_id, skill_name, source_domain, target_domain, relevance_score, proposed_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (proposal_id, name, source_domain, target_domain, score, time.time())
            )
            proposals.append(DomainProposal(
                skill_name=name,
                source_domain=source_domain,
                target_domain=target_domain,
                relevance_score=score,
                proposed_at=time.time()
            ))
        
        conn.commit()
        conn.close()
        
        return proposals

    def get_proposals(self, domain: str) -> list[DomainProposal]:
        """Get pending proposals for a domain."""
        conn = sqlite3.connect(self.shared_db_path)
        cursor = conn.execute(
            """SELECT skill_name, source_domain, target_domain, relevance_score, proposed_at
               FROM cross_domain_proposals
               WHERE target_domain = ? AND status = 'pending'
               ORDER BY relevance_score DESC""",
            (domain,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [
            DomainProposal(
                skill_name=row[0],
                source_domain=row[1],
                target_domain=row[2],
                relevance_score=row[3],
                proposed_at=row[4]
            ) for row in rows
        ]

    def accept_proposal(self, proposal_id: str) -> bool:
        """Accept a cross-domain proposal and import the skill."""
        conn = sqlite3.connect(self.shared_db_path)
        cursor = conn.execute(
            """SELECT s.name, s.code, s.domain
               FROM shared_skills s
               JOIN cross_domain_proposals p ON s.name = p.skill_name AND s.domain = p.source_domain
               WHERE p.proposal_id = ?""",
            (proposal_id,)
        )
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return False
        
        name, code, source_domain = row
        
        new_skill_id = f"imported_{name}_{int(time.time())}"
        conn.execute(
            """INSERT INTO shared_skills (skill_id, name, domain, code, last_synced)
               VALUES (?, ?, ?, ?, ?)""",
            (new_skill_id, name, source_domain, code, time.time())
        )
        
        conn.execute(
            "UPDATE cross_domain_proposals SET status = 'accepted' WHERE proposal_id = ?",
            (proposal_id,)
        )
        
        conn.commit()
        conn.close()
        
        return True

    def sync_all_domains(self) -> dict[str, Any]:
        """Get sync status across all registered domains."""
        conn = sqlite3.connect(self.shared_db_path)
        
        cursor = conn.execute("SELECT domain, instance_id, last_seen FROM swarm_domains")
        domains = cursor.fetchall()
        
        cursor = conn.execute("SELECT COUNT(*), AVG(cross_domain_score) FROM shared_skills")
        stats = cursor.fetchone()
        
        conn.close()
        
        return {
            "registered_domains": len(domains),
            "total_shared_skills": stats[0] or 0,
            "average_cross_score": stats[1] or 0.0,
            "domains": [
                {"domain": d[0], "instance": d[1], "last_seen": d[2]}
                for d in domains
            ]
        }
