"""Tests for fine-tune dataset building, scoring, and upload flow."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from archon.core.approval_gate import ApprovalGate
from archon.finetune.dataset_builder import DatasetBuilder, TrainingExample
from archon.finetune.quality_scorer import QualityScorer
from archon.finetune.upload import FineTuneUploader
from archon.memory.store import MemoryStore
from archon.memory.vector_index import VectorIndex


class _DeterministicEmbedder:
    def embed(self, text: str) -> list[float]:
        if "healthcare" in text.lower():
            return [1.0, 0.0, 0.0]
        return [0.3, 0.3, 0.4]

    def close(self) -> None:
        return None


def _tmp_path(name: str) -> Path:
    root = Path("archon/tests/_tmp_finetune")
    root.mkdir(parents=True, exist_ok=True)
    folder = root / f"{name}-{uuid.uuid4().hex[:8]}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _example(prompt: str, completion: str, idx: int = 1) -> TrainingExample:
    return TrainingExample(
        example_id=f"ex-{idx}",
        prompt=prompt,
        completion=completion,
        quality_score=0.9,
        source_memory_ids=[f"m-{idx}"],
        source_chains=[],
    )


def test_dataset_builder_build_from_memories_returns_examples_with_fields() -> None:
    tmp = _tmp_path("build")
    store = MemoryStore(
        db_path=str(tmp / "memory.sqlite3"),
        embedder=_DeterministicEmbedder(),
        vector_index=VectorIndex(backend="python"),
    )
    try:
        store.add(
            content="Draft outreach for Healthcare SMB founders in Mumbai.",
            role="user",
            session_id="s-1",
            tenant_id="tenant-a",
        )
        store.add(
            content=(
                "Here is a detailed outreach plan for Healthcare SMB founders in Mumbai. "
                "Start with local compliance pain points, map decision makers, and sequence "
                "follow-ups with evidence-backed ROI."
            ),
            role="assistant",
            session_id="s-1",
            tenant_id="tenant-a",
        )

        builder = DatasetBuilder(memory_store=store, icp_keywords=["healthcare", "smb", "mumbai"])
        examples = builder.build_from_memories("tenant-a", min_quality=0.0)

        assert examples
        item = examples[0]
        assert isinstance(item, TrainingExample)
        assert item.example_id
        assert item.prompt
        assert item.completion
        assert isinstance(item.quality_score, float)
        assert 0.0 <= item.quality_score <= 1.0
        assert len(item.source_memory_ids) == 2
        assert item.source_chains == []
    finally:
        store.close()


def test_dataset_builder_min_quality_filter_removes_low_scored_examples() -> None:
    tmp = _tmp_path("filter")
    store = MemoryStore(
        db_path=str(tmp / "memory.sqlite3"),
        embedder=_DeterministicEmbedder(),
        vector_index=VectorIndex(backend="python"),
    )
    try:
        store.add(
            content="Need a full GTM plan for Healthcare SMB.",
            role="user",
            session_id="s-2",
            tenant_id="tenant-a",
        )
        store.add(
            content="Sure.",
            role="assistant",
            session_id="s-2",
            tenant_id="tenant-a",
        )

        builder = DatasetBuilder(memory_store=store, icp_keywords=["healthcare", "smb"])
        examples = builder.build_from_memories("tenant-a", min_quality=0.7)

        assert examples == []
    finally:
        store.close()


def test_dataset_builder_export_jsonl_writes_messages_shape() -> None:
    tmp = _tmp_path("jsonl")
    output = tmp / "openai.jsonl"
    builder = DatasetBuilder(
        memory_store=MemoryStore(
            db_path=str(tmp / "mem.sqlite3"),
            embedder=_DeterministicEmbedder(),
            vector_index=VectorIndex(backend="python"),
        )
    )
    builder.export_jsonl(
        [_example("Plan a rollout", "Here is the rollout plan with milestones.")],
        output,
    )

    lines = output.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert "messages" in payload
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][1]["role"] == "assistant"


def test_dataset_builder_export_alpaca_writes_expected_fields() -> None:
    tmp = _tmp_path("alpaca")
    output = tmp / "alpaca.jsonl"
    builder = DatasetBuilder(
        memory_store=MemoryStore(
            db_path=str(tmp / "mem.sqlite3"),
            embedder=_DeterministicEmbedder(),
            vector_index=VectorIndex(backend="python"),
        )
    )
    builder.export_alpaca(
        [_example("Classify the intent", "The user intent is product comparison.")],
        output,
    )

    lines = output.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])
    assert set(payload) == {"instruction", "input", "output"}
    assert payload["instruction"] == "Classify the intent"
    assert payload["output"].startswith("The user intent")


def test_dataset_builder_deduplicate_drops_high_jaccard_examples() -> None:
    tmp = _tmp_path("dedupe")
    builder = DatasetBuilder(
        memory_store=MemoryStore(
            db_path=str(tmp / "mem.sqlite3"),
            embedder=_DeterministicEmbedder(),
            vector_index=VectorIndex(backend="python"),
        )
    )
    examples = [
        _example(
            "Summarize enterprise onboarding checklist",
            "Step 1 gather requirements and define milestones.",
            1,
        ),
        _example(
            "Summarize enterprise onboarding checklist!",
            "Step 1 gather requirements and define milestones",
            2,
        ),
        _example(
            "Write a churn rescue plan", "Analyze churn reasons and run win-back campaigns.", 3
        ),
    ]

    deduped = builder.deduplicate(examples)
    assert len(deduped) == 2
    assert deduped[0].example_id == "ex-1"
    assert deduped[1].example_id == "ex-3"


def test_quality_scorer_length_boundaries_and_linear_segment() -> None:
    scorer = QualityScorer()

    assert scorer.length_score("tiny") == 0.0
    assert scorer.length_score("x" * 600) == 1.0
    assert scorer.length_score("x" * 275) == pytest.approx(0.5, abs=1e-6)


def test_quality_scorer_score_batch_returns_expected_shape() -> None:
    scorer = QualityScorer()
    rows = [
        _example(
            "Explain GTM",
            "Detailed GTM plan for Healthcare SMB in Mumbai with staged execution.",
            1,
        ),
        _example(
            "Explain pricing", "Pricing rationale with competitor context and CAC guardrails.", 2
        ),
    ]

    scores = scorer.score_batch(rows)
    assert len(scores) == len(rows)
    assert all(isinstance(value, float) for value in scores)
    assert all(0.0 <= value <= 1.0 for value in scores)


def test_quality_scorer_score_returns_float_in_unit_range() -> None:
    scorer = QualityScorer()
    value = scorer.score(
        _example(
            "Create a launch checklist",
            "Create a launch checklist with owners, due dates, and rollback procedures.",
            1,
        )
    )
    assert isinstance(value, float)
    assert 0.0 <= value <= 1.0


def test_finetune_uploader_gate_fires_before_upload_and_returns_estimate() -> None:
    gate = ApprovalGate(auto_approve_in_test=False)
    events: list[dict[str, object]] = []
    gate_fired = {"value": False}

    async def sink(event: dict[str, object]) -> None:
        events.append(event)
        gate_fired["value"] = True
        gate.approve(str(event["action_id"]), approver="qa", notes="approved")

    def fake_upload(payload: str) -> dict[str, object]:
        assert gate_fired["value"] is True
        assert payload.strip()
        return {"id": "file-test-1", "status": "uploaded"}

    def fake_job(training_file_id: str, model: str, suffix: str) -> dict[str, object]:
        assert training_file_id == "file-test-1"
        assert model == "gpt-3.5-turbo"
        assert suffix == "archon"
        return {"id": "ftjob-test-1", "status": "succeeded"}

    uploader = FineTuneUploader(
        approval_gate=gate,
        event_sink=sink,
        openai_upload_file_fn=fake_upload,
        openai_create_job_fn=fake_job,
    )
    result = uploader.upload_openai(
        [
            _example(
                "Design customer onboarding",
                "Customer onboarding should include kickoff, enablement content, and weekly KPI review.",
                1,
            )
        ]
    )

    assert events
    assert events[0]["action"] == "external_api_call"
    assert result.job_id == "ftjob-test-1"
    assert result.example_count == 1
    assert isinstance(result.estimated_cost_usd, float)
    assert result.estimated_cost_usd > 0.0
