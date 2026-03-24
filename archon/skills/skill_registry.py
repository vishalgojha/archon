"""Skill registry for ARCHON skill routing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from archon.config import SUPPORTED_PROVIDERS

SKILL_STATES = {"STAGING", "ACTIVE", "REJECTED", "DISABLED"}
DEFAULT_STATE = "STAGING"


@dataclass(slots=True)
class SkillDefinition:
    name: str
    description: str = ""
    trigger_patterns: list[str] = field(default_factory=list)
    provider_preference: str | None = None
    cost_tier: str = "standard"
    state: str = DEFAULT_STATE
    version: int = 1
    created_at: float | None = None
    source_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "trigger_patterns": list(self.trigger_patterns),
            "provider_preference": self.provider_preference,
            "cost_tier": self.cost_tier,
            "state": self.state,
            "version": self.version,
        }
        if self.created_at is not None:
            payload["created_at"] = self.created_at
        return payload

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], *, source_path: Path | None = None
    ) -> "SkillDefinition":
        trigger_patterns = data.get("trigger_patterns")
        if isinstance(trigger_patterns, list):
            triggers = [str(item) for item in trigger_patterns if str(item).strip()]
        else:
            triggers = []
        provider = str(data.get("provider_preference") or "").strip().lower() or None
        if provider and provider not in SUPPORTED_PROVIDERS:
            provider = None
        cost_tier = str(data.get("cost_tier") or "standard").strip().lower() or "standard"
        state = str(data.get("state") or DEFAULT_STATE).strip().upper() or DEFAULT_STATE
        if state not in SKILL_STATES:
            state = DEFAULT_STATE
        version = _coerce_version(data.get("version", 1))
        created_at_raw = data.get("created_at")
        created_at = float(created_at_raw) if created_at_raw is not None else None
        return cls(
            name=str(data.get("name", "")).strip(),
            description=str(data.get("description", "")).strip(),
            trigger_patterns=triggers,
            provider_preference=provider,
            cost_tier=cost_tier,
            state=state,
            version=version,
            created_at=created_at,
            source_path=source_path,
        )


def _coerce_version(value: object) -> int:
    if value is None:
        return 1
    if isinstance(value, int):
        return max(1, value)
    if isinstance(value, float):
        return max(1, int(value))
    raw = str(value).strip()
    if not raw:
        return 1
    # Accept semver-ish strings like "1.0.0" by taking the leading int.
    match = re.match(r"(\d+)", raw)
    if match:
        return max(1, int(match.group(1)))
    return 1


@dataclass(slots=True)
class SkillMatch:
    skill: SkillDefinition
    pattern: str


class SkillRegistry:
    """Load and match skill definitions from YAML registry files."""

    def __init__(self, registry_dir: Path | None = None) -> None:
        self.registry_dir = registry_dir or (Path(__file__).resolve().parent / "registry")
        self._skills: dict[str, SkillDefinition] = {}
        self._load_errors: list[str] = []
        self.reload()

    def reload(self) -> None:
        self._skills = {}
        self._load_errors = []
        if not self.registry_dir.exists():
            return
        for path in sorted(self.registry_dir.glob("*.yml")) + sorted(
            self.registry_dir.glob("*.yaml")
        ):
            try:
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception as exc:  # pragma: no cover - defensive
                self._load_errors.append(f"{path.name}: {exc}")
                continue
            if not isinstance(payload, dict):
                self._load_errors.append(f"{path.name}: invalid YAML payload")
                continue
            skill = SkillDefinition.from_dict(payload, source_path=path)
            if not skill.name:
                self._load_errors.append(f"{path.name}: missing skill name")
                continue
            self._skills[skill.name] = skill

    def list_skills(self) -> list[SkillDefinition]:
        return sorted(self._skills.values(), key=lambda item: item.name)

    def get_skill(self, name: str) -> SkillDefinition | None:
        return self._skills.get(str(name).strip())

    def match_skill(
        self, task_description: str, *, include_staging: bool = False
    ) -> SkillMatch | None:
        normalized = str(task_description or "")
        if not normalized:
            return None
        candidates = [
            skill
            for skill in self._skills.values()
            if skill.state == "ACTIVE" or (include_staging and skill.state == "STAGING")
        ]
        for skill in sorted(candidates, key=lambda item: item.name):
            for pattern in skill.trigger_patterns:
                if _pattern_matches(pattern, normalized):
                    return SkillMatch(skill=skill, pattern=pattern)
        return None

    @property
    def load_errors(self) -> list[str]:
        return list(self._load_errors)


def _pattern_matches(pattern: str, text: str) -> bool:
    candidate = str(pattern or "").strip()
    if not candidate:
        return False
    try:
        return re.search(candidate, text, flags=re.IGNORECASE) is not None
    except re.error:
        return candidate.lower() in text.lower()
