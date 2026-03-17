"""Skill registry and creation utilities for ARCHON."""

from __future__ import annotations

from typing import TYPE_CHECKING

from archon.skills.skill_registry import SkillDefinition, SkillMatch, SkillRegistry

if TYPE_CHECKING:  # pragma: no cover - typing-only import
    from archon.skills.skill_creator import SkillCreator, SkillProposal


def __getattr__(name: str):
    if name in {"SkillCreator", "SkillProposal"}:
        from archon.skills.skill_creator import SkillCreator, SkillProposal

        return {"SkillCreator": SkillCreator, "SkillProposal": SkillProposal}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["SkillCreator", "SkillProposal", "SkillDefinition", "SkillMatch", "SkillRegistry"]
