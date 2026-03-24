"""Skill proposal and promotion workflow integrating with evolution audit trails."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from archon.config import ArchonConfig
from archon.core.approval_gate import ApprovalGate
from archon.core.orchestrator import Orchestrator
from archon.evolution.ab_tester import ABTester, SyntheticTask
from archon.evolution.audit_trail import AuditEntry, ImmutableAuditTrail
from archon.evolution.engine import WorkflowDefinition
from archon.skills.skill_registry import SkillDefinition, SkillMatch, SkillRegistry


@dataclass(slots=True)
class GapTask:
    task_id: str
    goal: str
    mode: str
    confidence: int | None
    fallback_used: bool
    providers_used: list[str]
    preferred_provider: str | None
    error: str | None = None


@dataclass(slots=True)
class SkillProposal:
    skill: SkillDefinition
    rationale: str
    gap_tasks: list[GapTask]


class SkillCreator:
    """Analyze gaps and create skill definitions with approval gating."""

    def __init__(
        self,
        *,
        config: ArchonConfig | None = None,
        registry: SkillRegistry | None = None,
        approval_gate: ApprovalGate | None = None,
        audit_trail: ImmutableAuditTrail | None = None,
    ) -> None:
        self.config = config or ArchonConfig()
        self.registry = registry or SkillRegistry()
        self.approval_gate = approval_gate or ApprovalGate(supervised_mode=True)
        self._owns_audit_trail = audit_trail is None
        self.audit_trail = audit_trail or ImmutableAuditTrail("archon_evolution_audit.sqlite3")

    def close(self) -> None:
        if self._owns_audit_trail:
            self.audit_trail.close()

    def find_gap_tasks(
        self,
        *,
        limit: int = 50,
        confidence_threshold: int = 70,
    ) -> list[GapTask]:
        entries = self.audit_trail.get_recent_entries(
            limit=limit * 3,
            event_types=["task_completed", "task_failed"],
        )
        gaps: list[GapTask] = []
        for entry in entries:
            payload = entry.payload
            if entry.event_type == "task_failed":
                gaps.append(_gap_from_payload(entry, payload))
                continue
            confidence = _parse_confidence(payload.get("confidence"))
            fallback = bool(payload.get("fallback_used", False))
            if confidence is None:
                continue
            if confidence < confidence_threshold or fallback:
                gaps.append(_gap_from_payload(entry, payload))
            if len(gaps) >= limit:
                break
        return gaps

    async def propose_skill(
        self,
        *,
        gap_tasks: list[GapTask],
        event_sink=None,
    ) -> SkillProposal | None:
        if not gap_tasks:
            return None
        proposal = self._build_proposal(gap_tasks)
        path = _skill_path(self.registry.registry_dir, proposal.skill.name)
        await self._require_approval(
            action="skill_propose",
            context={
                "agent": "skills.propose",
                "target": str(path),
                "preview": yaml.safe_dump(proposal.skill.to_dict(), sort_keys=False),
                "event_sink": event_sink,
            },
        )
        await _write_yaml(path, proposal.skill.to_dict())
        self.registry.reload()
        await self._append_audit(
            event_type="skill_proposed",
            skill=proposal.skill,
            payload={
                "rationale": proposal.rationale,
                "gap_tasks": [asdict(gap) for gap in proposal.gap_tasks],
            },
        )
        return proposal

    async def apply_skill(
        self,
        *,
        name: str,
        event_sink=None,
    ) -> dict[str, Any]:
        skill = self.registry.get_skill(name)
        if skill is None:
            raise ValueError(f"Unknown skill '{name}'.")
        if skill.state != "STAGING":
            raise ValueError(f"Skill '{name}' must be in STAGING state to apply.")

        tasks = self._build_trial_tasks(skill, count=10)
        trial = await self._run_ab_test(skill, tasks)
        success_rate = trial["success_rate"]
        threshold = float(self.config.skills.staging_threshold)
        await self._append_audit(
            event_type="skill_trial_completed",
            skill=skill,
            payload=trial,
        )

        if success_rate >= threshold:
            promoted = SkillDefinition(
                name=skill.name,
                description=skill.description,
                trigger_patterns=list(skill.trigger_patterns),
                provider_preference=skill.provider_preference,
                cost_tier=skill.cost_tier,
                state="ACTIVE",
                version=skill.version + 1,
                created_at=skill.created_at,
                source_path=skill.source_path,
            )
            path = skill.source_path or _skill_path(self.registry.registry_dir, skill.name)
            await self._require_approval(
                action="skill_promote",
                context={
                    "agent": "skills.apply",
                    "target": str(path),
                    "preview": yaml.safe_dump(promoted.to_dict(), sort_keys=False),
                    "event_sink": event_sink,
                },
            )
            await _write_yaml(path, promoted.to_dict())
            self.registry.reload()
            await self._append_audit(
                event_type="skill_promoted",
                skill=promoted,
                payload={"success_rate": success_rate, "threshold": threshold},
            )
            return {
                "status": "promoted",
                "skill": promoted.name,
                "success_rate": success_rate,
                "threshold": threshold,
            }

        await self._append_audit(
            event_type="skill_rolled_back",
            skill=skill,
            payload={"success_rate": success_rate, "threshold": threshold},
        )
        return {
            "status": "rejected",
            "skill": skill.name,
            "success_rate": success_rate,
            "threshold": threshold,
        }

    def _build_proposal(self, gap_tasks: list[GapTask]) -> SkillProposal:
        goals = [task.goal for task in gap_tasks if task.goal]
        keywords = _extract_keywords(goals)
        name = _skill_name_from_keywords(keywords)
        triggers = _trigger_patterns_from_keywords(keywords)
        provider = _most_common_provider(gap_tasks)
        avg_confidence = _average(
            [task.confidence for task in gap_tasks if task.confidence is not None]
        )
        cost_tier = "high" if avg_confidence < 60 else "standard"
        rationale = (
            "Gap analysis detected fallback routing or low confidence on recent tasks; "
            f"top keywords: {', '.join(keywords[:5]) or 'n/a'}."
        )
        skill = SkillDefinition(
            name=name,
            description=f"Handle tasks about {', '.join(keywords[:3]) or 'general gaps'}.",
            trigger_patterns=triggers,
            provider_preference=provider,
            cost_tier=cost_tier,
            state="STAGING",
            version=1,
            created_at=time.time(),
        )
        return SkillProposal(skill=skill, rationale=rationale, gap_tasks=gap_tasks)

    async def _run_ab_test(
        self, skill: SkillDefinition, tasks: list[SyntheticTask]
    ) -> dict[str, Any]:
        workflow_default = WorkflowDefinition(
            workflow_id="default",
            name="Default handler",
            steps=[],
            metadata={"type": "default"},
            version=1,
            created_at=time.time(),
        )
        workflow_skill = WorkflowDefinition(
            workflow_id=f"skill:{skill.name}",
            name=skill.name,
            steps=[],
            metadata=skill.to_dict(),
            version=skill.version,
            created_at=skill.created_at or time.time(),
        )

        tester = ABTester(
            executor=self._build_executor(skill),
            correctness_judge=_judge_confidence,
        )
        trial = await tester.run_trial(workflow_default, workflow_skill, tasks)
        success_rate = _compare_success_rate(trial)
        return {
            "success_rate": success_rate,
            "tasks": len(tasks),
            "aggregate_scores": trial.aggregate_scores,
            "recommended_winner": trial.recommended_winner,
        }

    def _build_executor(self, skill: SkillDefinition):
        async def _executor(workflow: WorkflowDefinition, task: SyntheticTask) -> dict[str, Any]:
            audit_trail = ImmutableAuditTrail(":memory:")
            orchestrator = Orchestrator(
                config=self.config,
                audit_trail=audit_trail,
            )
            start = time.perf_counter()
            try:
                if workflow.workflow_id.startswith("skill:"):
                    result = await orchestrator.execute(
                        goal=task.description,
                        mode="debate",
                        task_id=task.task_id,
                        skill_override=skill,
                        disable_skills=False,
                        emit_audit=False,
                    )
                else:
                    result = await orchestrator.execute(
                        goal=task.description,
                        mode="debate",
                        task_id=task.task_id,
                        disable_skills=True,
                        emit_audit=False,
                    )
                latency_ms = (time.perf_counter() - start) * 1000
                return {
                    "output": {
                        "confidence": result.confidence,
                        "final_answer": result.final_answer,
                    },
                    "latency_ms": latency_ms,
                    "cost_usd": float(result.budget.get("spent_usd", 0.0) or 0.0),
                }
            finally:
                await orchestrator.aclose()
                audit_trail.close()

        return _executor

    def _build_trial_tasks(self, skill: SkillDefinition, *, count: int) -> list[SyntheticTask]:
        matched: list[SyntheticTask] = []
        recent = self.audit_trail.get_recent_entries(
            limit=count * 4,
            event_types=["task_completed", "task_failed"],
        )
        for entry in recent:
            goal = str(entry.payload.get("goal", "")).strip()
            if not goal:
                continue
            match = _matches_skill(skill, goal)
            if not match:
                continue
            matched.append(
                SyntheticTask(
                    task_id=str(entry.payload.get("task_id") or entry.entry_id),
                    description=goal,
                    expected_output_schema={"confidence": "number"},
                    difficulty="medium",
                )
            )
            if len(matched) >= count:
                break
        while len(matched) < count:
            index = len(matched) + 1
            matched.append(
                SyntheticTask(
                    task_id=f"synthetic-{skill.name}-{index}",
                    description=(
                        f"Apply skill '{skill.name}' to {', '.join(skill.trigger_patterns[:2])}."
                    ),
                    expected_output_schema={"confidence": "number"},
                    difficulty="easy",
                )
            )
        return matched

    async def _require_approval(self, *, action: str, context: dict[str, Any]) -> None:
        action_id = f"skill-{uuid.uuid4().hex[:12]}"
        await self.approval_gate.check(action=action, context=context, action_id=action_id)

    async def _append_audit(
        self,
        *,
        event_type: str,
        skill: SkillDefinition,
        payload: dict[str, Any],
    ) -> None:
        entry = AuditEntry(
            entry_id=f"audit-{uuid.uuid4().hex[:12]}",
            timestamp=time.time(),
            event_type=event_type,
            workflow_id=f"skill:{skill.name}",
            actor="skills",
            payload=payload,
            prev_hash="",
            entry_hash="",
        )
        await asyncio.to_thread(self.audit_trail.append, entry)


async def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_dump(payload, sort_keys=False)
    await asyncio.to_thread(path.write_text, data, encoding="utf-8")


def _skill_path(registry_dir: Path, name: str) -> Path:
    safe = _slugify(name) or f"skill-{uuid.uuid4().hex[:6]}"
    path = registry_dir / f"{safe}.yaml"
    if path.exists():
        return registry_dir / f"{safe}-{uuid.uuid4().hex[:4]}.yaml"
    return path


def _slugify(value: str) -> str:
    sanitized = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized.strip("-")


def _gap_from_payload(entry: AuditEntry, payload: dict[str, Any]) -> GapTask:
    return GapTask(
        task_id=str(payload.get("task_id") or entry.entry_id),
        goal=str(payload.get("goal", "")),
        mode=str(payload.get("mode", "debate")),
        confidence=_parse_confidence(payload.get("confidence")),
        fallback_used=bool(payload.get("fallback_used", False)),
        providers_used=[str(item) for item in payload.get("providers_used", [])],
        preferred_provider=(
            str(payload.get("preferred_provider"))
            if payload.get("preferred_provider") is not None
            else None
        ),
        error=str(payload.get("error")) if payload.get("error") else None,
    )


def _parse_confidence(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _extract_keywords(goals: Iterable[str]) -> list[str]:
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "about",
        "your",
        "you",
        "what",
        "when",
        "where",
        "which",
        "how",
        "why",
        "does",
        "need",
    }
    counts: dict[str, int] = {}
    for goal in goals:
        tokens = ["".join(ch for ch in word.lower() if ch.isalnum()) for word in str(goal).split()]
        for token in tokens:
            if len(token) < 4 or token in stopwords:
                continue
            counts[token] = counts.get(token, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [item[0] for item in ordered[:8]]


def _skill_name_from_keywords(keywords: list[str]) -> str:
    if not keywords:
        return f"skill-gap-{uuid.uuid4().hex[:6]}"
    return f"skill-{'-'.join(keywords[:3])}"


def _trigger_patterns_from_keywords(keywords: list[str]) -> list[str]:
    patterns = [word for word in keywords[:5]]
    return patterns or ["gap"]


def _most_common_provider(tasks: list[GapTask]) -> str | None:
    counts: dict[str, int] = {}
    for task in tasks:
        for provider in task.providers_used:
            normalized = str(provider).strip().lower()
            if not normalized:
                continue
            counts[normalized] = counts.get(normalized, 0) + 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _average(values: Iterable[int | None]) -> float:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return 0.0
    return sum(cleaned) / len(cleaned)


def _judge_confidence(task: SyntheticTask, output: Any) -> float:
    if not isinstance(output, dict):
        return 0.0
    confidence = output.get("confidence")
    if confidence is None:
        return 0.0
    return max(0.0, min(1.0, float(confidence) / 100.0))


def _compare_success_rate(trial) -> float:  # type: ignore[no-untyped-def]
    if not trial.workflow_a_results or not trial.workflow_b_results:
        return 0.0
    default_map = {item.task_id: item for item in trial.workflow_a_results}
    skill_map = {item.task_id: item for item in trial.workflow_b_results}
    successes = 0
    total = 0
    for task_id, skill_result in skill_map.items():
        default_result = default_map.get(task_id)
        if default_result is None:
            continue
        total += 1
        if skill_result.correctness >= default_result.correctness:
            successes += 1
    if total == 0:
        return 0.0
    return round(successes / total, 6)


def _matches_skill(skill: SkillDefinition, goal: str) -> SkillMatch | None:
    text = str(goal or "")
    for pattern in skill.trigger_patterns:
        candidate = str(pattern or "").strip()
        if not candidate:
            continue
        try:
            if re.search(candidate, text, flags=re.IGNORECASE):
                return SkillMatch(skill=skill, pattern=pattern)
        except re.error:
            if candidate.lower() in text.lower():
                return SkillMatch(skill=skill, pattern=pattern)
    return None
