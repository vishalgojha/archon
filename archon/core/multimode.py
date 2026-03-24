"""Additional orchestration modes for ARCHON."""

from __future__ import annotations

import uuid
from typing import Any

from archon.config import ArchonConfig
from archon.core.cost_governor import CostGovernor
from archon.core.memory_store import MemoryStore
from archon.core.types import OrchestrationResult
from archon.evolution.audit_trail import ImmutableAuditTrail
from archon.providers import ProviderRouter


class SingleModeExecutor:
    """Execute tasks with a single LLM call."""

    def __init__(
        self,
        config: ArchonConfig,
        provider_router: ProviderRouter,
        cost_governor: CostGovernor,
        memory_store: MemoryStore,
        audit_trail: ImmutableAuditTrail | None = None,
    ) -> None:
        self.config = config
        self.provider_router = provider_router
        self.cost_governor = cost_governor
        self.memory_store = memory_store
        self.audit_trail = audit_trail

    async def execute(
        self,
        goal: str,
        task_id: str | None = None,
        language: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> OrchestrationResult:
        """Execute a task with a single LLM call.

        This mode is faster and cheaper than debate mode, but less reliable
        for complex tasks requiring multi-perspective analysis.
        """
        effective_task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
        self.cost_governor.start_task(effective_task_id)

        try:
            # Build prompt with context
            prompt = self._build_prompt(goal, context, language)

            # Execute single provider call
            response = await self.provider_router.invoke(
                role="primary",
                prompt=prompt,
                task_id=effective_task_id,
            )

            # Store in memory
            await self.memory_store.add_entry(
                task=goal,
                context={"language": language or "auto", "mode": "single"},
                actions_taken=["single_call"],
                causal_reasoning="Direct LLM execution chosen for speed.",
                actual_outcome=response.content,
                delta="Single-mode execution completed.",
                reuse_conditions="Use for simple tasks not requiring debate.",
            )

            # Record feedback
            self.provider_router.record_task_feedback(
                effective_task_id,
                quality_score=0.75,  # Default confidence for single mode
            )

            budget_snapshot = self.cost_governor.snapshot(effective_task_id)

            return OrchestrationResult(
                task_id=effective_task_id,
                goal=goal,
                mode="single",
                final_answer=response.content,
                confidence=75,
                budget=budget_snapshot,
            )

        finally:
            self.provider_router.clear_task_override(effective_task_id)
            self.provider_router.clear_task_routing(effective_task_id)

    def _build_prompt(
        self,
        goal: str,
        context: dict[str, Any] | None,
        language: str | None,
    ) -> str:
        """Build the prompt for single-mode execution."""
        prompt = f"Task: {goal}\n\n"

        if context:
            prompt += "Context:\n"
            for key, value in context.items():
                prompt += f"- {key}: {value}\n"
            prompt += "\n"

        if language and language != "auto":
            prompt += f"Please respond in {language}.\n"

        prompt += "Provide a clear, concise answer."
        return prompt


class PipelineModeExecutor:
    """Execute tasks through a sequential agent pipeline."""

    def __init__(
        self,
        config: ArchonConfig,
        provider_router: ProviderRouter,
        cost_governor: CostGovernor,
        memory_store: MemoryStore,
        audit_trail: ImmutableAuditTrail | None = None,
    ) -> None:
        self.config = config
        self.provider_router = provider_router
        self.cost_governor = cost_governor
        self.memory_store = memory_store
        self.audit_trail = audit_trail

    async def execute(
        self,
        goal: str,
        task_id: str | None = None,
        language: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> OrchestrationResult:
        """Execute a task through sequential agent stages.

        Pipeline stages:
        1. Research - gather information
        2. Analysis - analyze the information
        3. Synthesis - produce final answer

        This mode balances speed and reliability.
        """
        effective_task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
        self.cost_governor.start_task(effective_task_id)

        try:
            actions_taken: list[str] = []
            stage_results: dict[str, str] = {}

            # Stage 1: Research
            research_prompt = self._build_research_prompt(goal, context)
            research_response = await self.provider_router.invoke(
                role="primary",
                prompt=research_prompt,
                task_id=effective_task_id,
            )
            stage_results["research"] = research_response.content
            actions_taken.append("research")

            # Stage 2: Analysis
            analysis_prompt = self._build_analysis_prompt(goal, stage_results["research"])
            analysis_response = await self.provider_router.invoke(
                role="primary",
                prompt=analysis_prompt,
                task_id=effective_task_id,
            )
            stage_results["analysis"] = analysis_response.content
            actions_taken.append("analysis")

            # Stage 3: Synthesis
            synthesis_prompt = self._build_synthesis_prompt(
                goal, stage_results["research"], stage_results["analysis"], language
            )
            synthesis_response = await self.provider_router.invoke(
                role="primary",
                prompt=synthesis_prompt,
                task_id=effective_task_id,
            )
            actions_taken.append("synthesis")

            # Store in memory
            await self.memory_store.add_entry(
                task=goal,
                context={"language": language or "auto", "mode": "pipeline"},
                actions_taken=actions_taken,
                causal_reasoning="Pipeline execution for balanced speed/reliability.",
                actual_outcome=synthesis_response.content,
                delta="Pipeline-mode execution completed.",
                reuse_conditions="Use for tasks requiring structured analysis.",
            )

            # Record feedback
            self.provider_router.record_task_feedback(
                effective_task_id,
                quality_score=0.85,  # Higher confidence than single mode
            )

            budget_snapshot = self.cost_governor.snapshot(effective_task_id)

            return OrchestrationResult(
                task_id=effective_task_id,
                goal=goal,
                mode="pipeline",
                final_answer=synthesis_response.content,
                confidence=85,
                budget=budget_snapshot,
                debate={"stages": stage_results},
            )

        finally:
            self.provider_router.clear_task_override(effective_task_id)
            self.provider_router.clear_task_routing(effective_task_id)

    def _build_research_prompt(self, goal: str, context: dict[str, Any] | None) -> str:
        """Build prompt for research stage."""
        prompt = f"Research the following task: {goal}\n\n"
        if context:
            prompt += "Context:\n"
            for key, value in context.items():
                prompt += f"- {key}: {value}\n"
        prompt += "\nGather relevant information and key facts."
        return prompt

    def _build_analysis_prompt(self, goal: str, research: str) -> str:
        """Build prompt for analysis stage."""
        return f"""Task: {goal}

Research findings:
{research}

Analyze the research findings. Identify:
1. Key patterns and insights
2. Potential implications
3. Gaps or uncertainties

Provide structured analysis."""

    def _build_synthesis_prompt(
        self,
        goal: str,
        research: str,
        analysis: str,
        language: str | None,
    ) -> str:
        """Build prompt for synthesis stage."""
        prompt = f"""Task: {goal}

Research:
{research}

Analysis:
{analysis}

Synthesize a clear, actionable answer.
"""
        if language and language != "auto":
            prompt += f"Respond in {language}.\n"
        return prompt
