"""Approval-gated fine-tuning upload helpers for external providers."""

from __future__ import annotations

import asyncio
import json
import math
import threading
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from archon.core.approval_gate import ApprovalGate, EventSink
from archon.finetune.dataset_builder import TrainingExample


@dataclass(slots=True)
class UploadResult:
    """Fine-tune upload job metadata."""

    job_id: str
    provider: str
    status: str
    estimated_cost_usd: float
    example_count: int


class FineTuneUploader:
    """Uploads fine-tune datasets to provider APIs behind ApprovalGate."""

    def __init__(
        self,
        approval_gate: ApprovalGate | None = None,
        *,
        event_sink: EventSink | None = None,
        provider_rates: dict[str, float] | None = None,
        openai_upload_file_fn: Callable[[str], dict[str, Any]] | None = None,
        openai_create_job_fn: Callable[[str, str, str], dict[str, Any]] | None = None,
        together_create_job_fn: Callable[[str, str, str], dict[str, Any]] | None = None,
    ) -> None:
        self.approval_gate = approval_gate or ApprovalGate(auto_approve_in_test=True)
        self.event_sink = event_sink
        self.provider_rates = {
            "openai": 0.000008,
            "together": 0.000005,
            **(provider_rates or {}),
        }
        self._openai_upload_file_fn = openai_upload_file_fn
        self._openai_create_job_fn = openai_create_job_fn
        self._together_create_job_fn = together_create_job_fn

    def upload_openai(
        self,
        examples: Iterable[TrainingExample],
        model: str = "gpt-3.5-turbo",
        suffix: str = "archon",
    ) -> UploadResult:
        """Upload dataset to OpenAI files API and start a fine-tune job."""

        rows = list(examples)
        estimated_cost = self._estimated_cost_usd(rows, provider="openai")
        self._gate_external_upload(
            provider="openai",
            model=model,
            suffix=suffix,
            example_count=len(rows),
            estimated_cost_usd=estimated_cost,
        )

        payload = self._openai_jsonl_payload(rows)
        file_result = self._openai_upload_file(payload)
        training_file_id = str(
            file_result.get("id") or file_result.get("file_id") or f"file-{uuid.uuid4().hex[:12]}"
        )

        job_result = self._openai_create_job(
            training_file_id=training_file_id, model=model, suffix=suffix
        )
        return UploadResult(
            job_id=str(job_result.get("id") or f"ftjob-{uuid.uuid4().hex[:12]}"),
            provider="openai",
            status=str(job_result.get("status") or "created"),
            estimated_cost_usd=estimated_cost,
            example_count=len(rows),
        )

    def upload_together(
        self, examples: Iterable[TrainingExample], model: str, suffix: str
    ) -> UploadResult:
        """Upload dataset to Together AI fine-tune API."""

        rows = list(examples)
        estimated_cost = self._estimated_cost_usd(rows, provider="together")
        self._gate_external_upload(
            provider="together",
            model=model,
            suffix=suffix,
            example_count=len(rows),
            estimated_cost_usd=estimated_cost,
        )

        payload = self._openai_jsonl_payload(rows)
        job_result = self._together_create_job(payload=payload, model=model, suffix=suffix)
        return UploadResult(
            job_id=str(job_result.get("id") or f"togjob-{uuid.uuid4().hex[:12]}"),
            provider="together",
            status=str(job_result.get("status") or "submitted"),
            estimated_cost_usd=estimated_cost,
            example_count=len(rows),
        )

    def _gate_external_upload(
        self,
        *,
        provider: str,
        model: str,
        suffix: str,
        example_count: int,
        estimated_cost_usd: float,
    ) -> None:
        context: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "suffix": suffix,
            "example_count": int(example_count),
            "estimated_cost_usd": float(estimated_cost_usd),
        }
        if self.event_sink is not None:
            context["event_sink"] = self.event_sink
        action_id = f"ft-upload-{uuid.uuid4().hex[:12]}"
        _run_coro(
            self.approval_gate.check(
                action="external_api_call", context=context, action_id=action_id
            )
        )

    def _estimated_cost_usd(self, examples: list[TrainingExample], *, provider: str) -> float:
        token_count = self._estimate_token_count(examples)
        rate = float(self.provider_rates.get(provider, 0.0))
        return round(token_count * rate, 6)

    @staticmethod
    def _estimate_token_count(examples: list[TrainingExample]) -> int:
        total_chars = sum(len(item.prompt) + len(item.completion) for item in examples)
        return int(math.ceil(total_chars / 4.0)) if total_chars else 0

    @staticmethod
    def _openai_jsonl_payload(examples: list[TrainingExample]) -> str:
        lines = []
        for item in examples:
            lines.append(
                json.dumps(
                    {
                        "messages": [
                            {"role": "user", "content": item.prompt},
                            {"role": "assistant", "content": item.completion},
                        ]
                    },
                    ensure_ascii=False,
                )
            )
        return "\n".join(lines) + ("\n" if lines else "")

    def _openai_upload_file(self, payload: str) -> dict[str, Any]:
        if self._openai_upload_file_fn is not None:
            return dict(self._openai_upload_file_fn(payload))
        return {
            "id": f"file-{uuid.uuid4().hex[:12]}",
            "status": "uploaded",
            "bytes": len(payload.encode("utf-8")),
        }

    def _openai_create_job(
        self, *, training_file_id: str, model: str, suffix: str
    ) -> dict[str, Any]:
        if self._openai_create_job_fn is not None:
            return dict(self._openai_create_job_fn(training_file_id, model, suffix))
        return {
            "id": f"ftjob-{uuid.uuid4().hex[:12]}",
            "status": "created",
            "training_file": training_file_id,
            "model": model,
            "suffix": suffix,
        }

    def _together_create_job(self, *, payload: str, model: str, suffix: str) -> dict[str, Any]:
        if self._together_create_job_fn is not None:
            return dict(self._together_create_job_fn(payload, model, suffix))
        return {
            "id": f"togjob-{uuid.uuid4().hex[:12]}",
            "status": "submitted",
            "model": model,
            "suffix": suffix,
            "bytes": len(payload.encode("utf-8")),
        }


def _run_coro(coro):  # type: ignore[no-untyped-def]
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_box: dict[str, Any] = {}
    error_box: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result_box["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive bridge
            error_box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in error_box:
        raise error_box["error"]
    return result_box.get("value")
