"""Tests for skill registry and creator."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from archon.core.approval_gate import ApprovalGate
from archon.evolution.audit_trail import AuditEntry, ImmutableAuditTrail
from archon.skills.skill_creator import SkillCreator
from archon.skills.skill_registry import SkillRegistry


def test_skill_registry_matches_patterns(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    skill_yaml = registry_dir / "research.yaml"
    skill_yaml.write_text(
        """
name: research-skill
description: research tasks
trigger_patterns:
  - research
provider_preference: openai
cost_tier: standard
state: ACTIVE
""".strip()
        + "\n",
        encoding="utf-8",
    )

    registry = SkillRegistry(registry_dir=registry_dir)
    match = registry.match_skill("Need research on pricing trends")
    assert match is not None
    assert match.skill.name == "research-skill"


@pytest.mark.asyncio
async def test_skill_creator_stages_proposal(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    audit = ImmutableAuditTrail(":memory:")
    audit.append(
        AuditEntry(
            entry_id="audit-1",
            timestamp=time.time(),
            event_type="task_completed",
            workflow_id="task:test",
            actor="orchestrator",
            payload={
                "task_id": "task-1",
                "goal": "Investigate churn drivers",
                "mode": "debate",
                "confidence": 50,
                "fallback_used": False,
                "providers_used": ["openai"],
                "preferred_provider": "openai",
                "budget": {"spent_usd": 0.2},
            },
            prev_hash="",
            entry_hash="",
        )
    )
    registry = SkillRegistry(registry_dir=registry_dir)
    gate = ApprovalGate(auto_approve_in_test=True)
    creator = SkillCreator(
        registry=registry,
        approval_gate=gate,
        audit_trail=audit,
    )

    gaps = creator.find_gap_tasks(limit=5, confidence_threshold=70)
    proposal = await creator.propose_skill(gap_tasks=gaps, event_sink=None)

    assert proposal is not None
    assert proposal.skill.state == "STAGING"
    assert any(path.suffix == ".yaml" for path in registry_dir.iterdir())
    creator.close()
    audit.close()
