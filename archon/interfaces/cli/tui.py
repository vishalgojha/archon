"""Interactive terminal UI for ARCHON orchestration sessions."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import click

from archon.config import ArchonConfig
from archon.core.orchestrator import OrchestrationResult, Orchestrator
from archon.interfaces.cli.tui_onboarding import (
    OnboardingCallbacks,
    run_launcher,
    run_setup_wizard,
)
from archon.interfaces.cli.tui_render import preview, render_screen


@dataclass(slots=True)
class _SessionState:
    mode: str
    live_provider_calls: bool
    context: dict[str, Any]
    history: list[dict[str, Any]] = field(default_factory=list)
    transcript: list[dict[str, str]] = field(default_factory=list)
    running: bool = False


def _resolve_mode(mode: str, goal: str) -> str:
    if mode != "auto":
        return mode
    lowered = goal.lower()
    growth_hints = ("lead", "pipeline", "outreach", "growth", "revenue", "churn", "prospect")
    return "growth" if any(hint in lowered for hint in growth_hints) else "debate"


def _render(state: _SessionState) -> None:
    click.echo(
        render_screen(
            mode=state.mode,
            live_provider_calls=state.live_provider_calls,
            context=state.context,
            transcript=state.transcript,
            history=state.history,
            running=state.running,
        ),
        nl=False,
    )


def _append_message(state: _SessionState, *, title: str, body: str, tone: str) -> None:
    state.transcript.append({"title": title, "body": body, "tone": tone})


def _format_status(state: _SessionState) -> str:
    context_keys = ", ".join(sorted(state.context)) if state.context else "none"
    return (
        f"Mode={state.mode} | live_providers={'on' if state.live_provider_calls else 'off'} | "
        f"context_keys={context_keys} | history={len(state.history)}"
    )


def _format_history(state: _SessionState) -> str:
    if not state.history:
        return "No completed tasks yet."
    return "\n".join(
        f"{index}. [{item['mode']}] {item['goal']} -> "
        f"{item['confidence']}% (${item['spent_usd']:.4f})"
        for index, item in enumerate(state.history, start=1)
    )


def _format_result(result: OrchestrationResult) -> str:
    lines = [
        f"Task: {result.task_id}",
        f"Mode: {result.mode}",
        f"Confidence: {result.confidence}%",
        f"Budget spent: ${float(result.budget.get('spent_usd', 0.0) or 0.0):.4f}",
        "",
        result.final_answer,
    ]
    if result.debate:
        lines.extend(["", "Debate rounds:"])
        for index, round_payload in enumerate(result.debate.get("rounds", []), start=1):
            lines.append(
                f"{index}. {round_payload.get('agent', 'unknown')} "
                f"{int(round_payload.get('confidence', 0) or 0)}% :: "
                f"{preview(str(round_payload.get('output', '')))}"
            )
        dissent = result.debate.get("dissent", [])
        if dissent:
            lines.append("Dissent:")
            for item in dissent[:2]:
                lines.append(f"- {preview(str(item))}")
    if result.growth:
        reports = list(result.growth.get("agent_reports", []))
        if reports:
            lines.extend(["", "Growth agent reports:"])
            for report in reports:
                lines.append(
                    f"- {report.get('agent', 'unknown')} "
                    f"{int(report.get('confidence', 0) or 0)}% :: "
                    f"{preview(str(report.get('output', '')))}"
                )
        actions = sorted(
            list(result.growth.get("recommended_actions", [])),
            key=lambda item: int(item.get("priority", 99)),
        )
        if actions:
            lines.append("Top actions:")
            for action in actions[:5]:
                lines.append(
                    f"- P{int(action.get('priority', 99))} "
                    f"{str(action.get('objective', 'Untitled action')).strip()}"
                )
    return "\n".join(lines)


async def _read_session_line(prompt: str) -> str:
    return await asyncio.to_thread(_sync_read_session_line, prompt)


def _sync_read_session_line(prompt: str) -> str:
    click.echo(prompt, nl=False)
    return click.get_text_stream("stdin").readline().rstrip("\r\n")


async def _prompt_approval_decision(event: dict[str, Any]) -> bool:
    return await asyncio.to_thread(_sync_prompt_approval_decision, event)


def _sync_prompt_approval_decision(event: dict[str, Any]) -> bool:
    context_blob = json.dumps(event.get("context", {}), sort_keys=True)
    click.echo(f"Approve {event.get('action_type', 'action')}? context={context_blob}")
    return bool(click.confirm("Approve", default=False))


async def _handle_event(
    state: _SessionState,
    orchestrator: Orchestrator,
    event: dict[str, Any],
) -> None:
    event_type = str(event.get("type", "")).strip().lower()
    if event_type == "task_started":
        _append_message(
            state,
            title="Task started",
            body=f"{event.get('mode', 'unknown')} | {event.get('task_id', 'task')}",
            tone="system",
        )
        _render(state)
        return
    if event_type == "debate_round_completed":
        _append_message(
            state,
            title=(
                f"{event.get('agent', 'unknown')} | "
                f"round {int(event.get('round', 0) or 0)}/"
                f"{int(event.get('total_rounds', 0) or 0)}"
            ),
            body=(
                f"Confidence: {int(event.get('confidence', 0) or 0)}%\n"
                f"{event.get('output_preview', '')}"
            ),
            tone="event",
        )
        _render(state)
        return
    if event_type == "growth_agent_completed":
        _append_message(
            state,
            title=f"{event.get('agent', 'unknown')} | growth",
            body=f"Confidence: {int(event.get('confidence', 0) or 0)}%",
            tone="event",
        )
        _render(state)
        return
    if event_type == "approval_required":
        request_id = str(event.get("request_id", "")).strip()
        _append_message(
            state,
            title="Approval required",
            body=(
                f"{event.get('action_type', 'action')} requested "
                f"({event.get('risk_level', 'unknown')})"
            ),
            tone="system",
        )
        _render(state)
        approved = await _prompt_approval_decision(event)
        if approved:
            orchestrator.approval_gate.approve(
                request_id,
                approver="tui-user",
                notes="approved_in_agentic_tui",
            )
            _append_message(
                state,
                title="Approval resolved",
                body=f"approved {request_id}",
                tone="system",
            )
            _render(state)
            return
        orchestrator.approval_gate.deny(
            request_id,
            reason="denied_in_agentic_tui",
            approver="tui-user",
        )
        _append_message(
            state,
            title="Approval resolved",
            body=f"denied {request_id}",
            tone="error",
        )
        _render(state)
        return
    if event_type == "approval_resolved":
        _append_message(
            state,
            title="Approval event",
            body=(
                f"resolved {event.get('request_id', '')} "
                f"approved={bool(event.get('approved', False))}"
            ),
            tone="system",
        )
        _render(state)
        return
    if event_type == "task_completed":
        budget = event.get("budget", {})
        _append_message(
            state,
            title="Run complete",
            body=(
                f"{event.get('mode', 'unknown')} | "
                f"confidence={int(event.get('confidence', 0) or 0)}% | "
                f"spent=${float(budget.get('spent_usd', 0.0) or 0.0):.4f}"
            ),
            tone="system",
        )
        _render(state)


async def _handle_command(
    state: _SessionState,
    raw_value: str,
    *,
    config_path: str,
    onboarding: OnboardingCallbacks | None,
    config_ref: dict[str, ArchonConfig],
) -> bool:
    command, _, arg_text = raw_value[1:].partition(" ")
    command = command.strip().lower()
    arg_text = arg_text.strip()

    if command in {"quit", "exit"}:
        _append_message(state, title="Session", body="Closing ARCHON Agentic TUI.", tone="system")
        return False
    if command == "help":
        _append_message(
            state,
            title="Commands",
            body="\n".join(
                [
                    "/mode <debate|growth|auto>",
                    "/context <json-object>",
                    "/context",
                    "/clear-context",
                    "/live <on|off>",
                    "/status",
                    "/history",
                    "/setup",
                    "/reset",
                    "/quit",
                ]
            ),
            tone="system",
        )
        return True
    if command == "mode":
        if arg_text not in {"debate", "growth", "auto"}:
            _append_message(
                state,
                title="Mode update failed",
                body="Mode must be debate, growth, or auto.",
                tone="error",
            )
            return True
        state.mode = arg_text
        _append_message(
            state,
            title="Mode updated",
            body=f"Mode set to {state.mode}.",
            tone="system",
        )
        return True
    if command == "context":
        if not arg_text:
            _append_message(
                state,
                title="Session context",
                body=json.dumps(state.context, indent=2, sort_keys=True),
                tone="system",
            )
            return True
        try:
            payload = json.loads(arg_text)
        except json.JSONDecodeError as exc:
            _append_message(
                state,
                title="Context update failed",
                body=f"Context must be valid JSON: {exc}",
                tone="error",
            )
            return True
        if not isinstance(payload, dict):
            _append_message(
                state,
                title="Context update failed",
                body="Context must decode to a JSON object.",
                tone="error",
            )
            return True
        state.context = payload
        _append_message(
            state,
            title="Context updated",
            body=f"Context updated with {len(state.context)} keys.",
            tone="system",
        )
        return True
    if command == "clear-context":
        state.context = {}
        _append_message(state, title="Context updated", body="Context cleared.", tone="system")
        return True
    if command == "live":
        if arg_text not in {"on", "off"}:
            _append_message(
                state,
                title="Live mode update failed",
                body="Live mode must be 'on' or 'off'.",
                tone="error",
            )
            return True
        state.live_provider_calls = arg_text == "on"
        _append_message(
            state,
            title="Live mode updated",
            body=f"Live providers {'enabled' if state.live_provider_calls else 'disabled'}.",
            tone="system",
        )
        return True
    if command == "status":
        _append_message(state, title="Session status", body=_format_status(state), tone="system")
        return True
    if command == "history":
        _append_message(state, title="Run history", body=_format_history(state), tone="system")
        return True
    if command == "setup":
        if onboarding is None:
            _append_message(
                state,
                title="Setup unavailable",
                body="This session was not given onboarding callbacks.",
                tone="error",
            )
            return True
        config_ref["config"], summary = await run_setup_wizard(
            config_path=config_path,
            onboarding=onboarding,
            current_config=config_ref["config"],
        )
        _append_message(state, title="Setup complete", body=summary, tone="system")
        return True
    if command == "reset":
        state.transcript = []
        _append_message(
            state,
            title="Session reset",
            body="Transcript cleared. Session settings were preserved.",
            tone="system",
        )
        return True
    _append_message(
        state,
        title="Unknown command",
        body="Unknown command. Type /help for available commands.",
        tone="error",
    )
    return True


async def run_agentic_tui(
    *,
    config: ArchonConfig,
    initial_mode: str = "auto",
    live_provider_calls: bool = False,
    initial_context: dict[str, Any] | None = None,
    config_path: str = "config.archon.yaml",
    onboarding: OnboardingCallbacks | None = None,
    show_launcher: bool = False,
) -> None:
    """Run the interactive ARCHON terminal UI.

    Example:
        >>> await run_agentic_tui(config=ArchonConfig(), initial_mode="debate")
        >>> True
        True
    """

    state = _SessionState(
        mode=initial_mode,
        live_provider_calls=live_provider_calls,
        context=dict(initial_context or {}),
    )
    config_ref = {"config": config}
    if show_launcher:
        launcher_result = await run_launcher(
            config=config_ref["config"],
            config_path=config_path,
            mode=state.mode,
            live_provider_calls=state.live_provider_calls,
            onboarding=onboarding,
        )
        if not launcher_result.start:
            return
        config_ref["config"] = launcher_result.config
        state.mode = launcher_result.mode
        state.live_provider_calls = launcher_result.live_provider_calls
        for note in launcher_result.notes:
            _append_message(
                state,
                title=note["title"],
                body=note["body"],
                tone=note["tone"],
            )
    _append_message(
        state,
        title="ARCHON",
        body=(
            "ARCHON just came online. Give me a goal, a workflow, or a revenue problem and "
            "I will route the right swarm."
        ),
        tone="assistant",
    )

    while True:
        _render(state)
        raw_value = (await _read_session_line("> ")).strip()
        if not raw_value:
            continue
        if raw_value.startswith("/"):
            if not await _handle_command(
                state,
                raw_value,
                config_path=config_path,
                onboarding=onboarding,
                config_ref=config_ref,
            ):
                _render(state)
                return
            continue

        effective_mode = _resolve_mode(state.mode, raw_value)
        _append_message(state, title="You", body=raw_value, tone="user")
        state.running = True
        _render(state)
        orchestrator = Orchestrator(
            config=config_ref["config"],
            live_provider_calls=state.live_provider_calls,
        )
        try:
            result = await orchestrator.execute(
                goal=raw_value,
                mode=effective_mode,  # type: ignore[arg-type]
                context=dict(state.context),
                event_sink=lambda event: _handle_event(state, orchestrator, event),
            )
        except Exception as exc:
            _append_message(state, title="Task failed", body=str(exc), tone="error")
        else:
            state.history.append(
                {
                    "goal": raw_value,
                    "mode": result.mode,
                    "confidence": result.confidence,
                    "spent_usd": float(result.budget.get("spent_usd", 0.0) or 0.0),
                }
            )
            _append_message(
                state,
                title="ARCHON",
                body=_format_result(result),
                tone="assistant",
            )
        finally:
            state.running = False
            await orchestrator.aclose()
