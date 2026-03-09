from __future__ import annotations

import asyncio
import inspect
import threading
from dataclasses import dataclass
from typing import Any

import click

from archon.cli import renderer
from archon.cli.copy import COMMAND_COPY

try:  # pragma: no cover - optional dependency
    from rich.console import Console
    from rich.live import Live
except Exception:  # pragma: no cover - optional dependency
    Console = None
    Live = None


@dataclass(slots=True)
class CommandOutcome:
    data: dict[str, Any]
    next_steps: bool = True


class CommandSession:
    def __init__(self, command_id: str) -> None:
        self.command_id = command_id
        self._console = Console() if Console is not None else None
        self._states = ["pending"] * len(COMMAND_COPY[command_id]["steps"])
        self._live = None

    def print(self, renderable: Any) -> None:
        if self._console is not None and not isinstance(renderable, str):
            self._console.print(renderable)
            return
        click.echo(str(renderable))

    def start(self) -> None:
        self.print(renderer.what_panel(self.command_id))
        panel = renderer.steps_table(self.command_id, self._states)
        if Live is None or self._console is None or isinstance(panel, str):
            self.print(panel)
            return
        self._live = Live(panel, console=self._console, refresh_per_second=4)
        self._live.start()

    def update_step(self, index: int, state: str) -> None:
        if not 0 <= index < len(self._states):
            return
        self._states[index] = state
        if self._live is None:
            return
        self._live.update(renderer.steps_table(self.command_id, self._states), refresh=True)

    def run_step(self, index: int, func, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.update_step(index, "running")
        try:
            result = func(*args, **kwargs)
        except Exception:
            self.update_step(index, "error")
            raise
        self.update_step(index, "success")
        return result

    async def run_step_async(self, index: int, func, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.update_step(index, "running")
        try:
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            self.update_step(index, "error")
            raise
        self.update_step(index, "success")
        return result

    def finish(self, outcome: CommandOutcome) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
        self.print(renderer.result_panel(self.command_id, outcome.data))
        if outcome.next_steps:
            self.print(renderer.next_steps_panel(self.command_id))

    def close(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None


class ArchonCommand:
    command_id: str = ""

    def __init__(self, bindings: Any) -> None:
        self.bindings = bindings

    def run(self, session: CommandSession, **kwargs) -> CommandOutcome | dict[str, Any]:  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def invoke(self, **kwargs) -> CommandOutcome:
        session = CommandSession(self.command_id)
        session.start()
        try:
            result = self.run(session=session, **kwargs)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            if isinstance(result, CommandOutcome):
                outcome = result
            else:
                outcome = CommandOutcome(dict(result or {}))
            session.finish(outcome)
            return outcome
        except click.ClickException as exc:
            session.close()
            session.print(
                renderer.result_panel(
                    self.command_id,
                    {"result_key": "failure", "status": "failed", "error": str(exc)},
                )
            )
            raise
        except Exception as exc:
            session.close()
            session.print(
                renderer.result_panel(
                    self.command_id,
                    {"result_key": "failure", "status": "failed", "error": str(exc)},
                )
            )
            raise click.ClickException(str(exc)) from exc


class PlaceholderCommand(ArchonCommand):
    def run(self, session: CommandSession, **kwargs) -> CommandOutcome:  # type: ignore[no-untyped-def]
        if COMMAND_COPY[self.command_id]["steps"]:
            session.update_step(0, "running")
            session.update_step(0, "success")
        session.close()
        session.print(renderer.placeholder_panel(self.command_id))
        return CommandOutcome({"command": self.command_id}, next_steps=False)


class TaskLiveDisplay:
    def __init__(self) -> None:
        self._console = Console() if Console is not None else None
        self._live = None
        self.state = {
            "status": "starting",
            "mode": "-",
            "agent": "-",
            "round": "-",
            "cost": "-",
            "event": "-",
        }

    def start(self) -> None:
        panel = renderer.live_task_panel(self.state)
        if Live is None or self._console is None or isinstance(panel, str):
            renderer.emit(panel)
            return
        self._live = Live(panel, console=self._console, refresh_per_second=2)
        self._live.start()

    def stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def update(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", "")).strip().lower()
        self.state["event"] = event_type or self.state["event"]
        self.state["mode"] = str(event.get("mode", self.state["mode"]))
        if event_type in {"agent_start", "agent_end", "growth_agent_completed"}:
            self.state["agent"] = str(event.get("agent", self.state["agent"]))
        if event_type == "task_started":
            self.state["status"] = "running"
        elif event_type == "task_completed":
            self.state["status"] = "completed"
        elif event_type == "debate_round_completed":
            current = int(event.get("round", 0) or 0)
            total = int(event.get("total_rounds", 0) or 0)
            self.state["round"] = f"{current}/{total}" if total else str(current)
            self.state["agent"] = str(event.get("agent", self.state["agent"]))
        elif event_type == "cost_update":
            spent = float(event.get("spent", 0.0) or 0.0)
            limit = float(event.get("budget", 0.0) or 0.0)
            self.state["cost"] = f"${spent:.4f}/${limit:.4f}"
        if self._live is not None:
            self._live.update(renderer.live_task_panel(self.state), refresh=True)


def approval_prompt(
    *,
    gate,
    event: dict[str, Any],
    timeout_seconds: float = 30.0,
) -> bool:  # type: ignore[no-untyped-def]
    request_id = str(event.get("request_id", "")).strip()
    context = event.get("context", {}) if isinstance(event.get("context"), dict) else {}
    renderer.emit(
        renderer.approval_panel(
            {
                "agent": context.get("agent", "agent"),
                "action": event.get("action_type", event.get("action", "action")),
                "target": context.get("target", context.get("resource", "-")),
                "preview": context.get("preview", context.get("content", "-")),
                "countdown": int(timeout_seconds),
            }
        )
    )
    click.echo("y/N: ", nl=False)
    answer: dict[str, str] = {}

    def _read() -> None:
        answer["value"] = click.get_text_stream("stdin").readline().strip().lower()

    thread = threading.Thread(target=_read, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    approved = answer.get("value", "") in {"y", "yes"}
    if thread.is_alive():
        gate.deny(request_id, reason="timeout", approver="archon-cli")
        renderer.emit(
            renderer.detail_panel(
                "approval",
                [renderer.flow_message("approval_gate", "timed_out", {"action": event.get("action_type", "action")})],
            )
        )
        return False
    if approved:
        gate.approve(request_id, approver="archon-cli", notes="approved_in_cli")
        renderer.emit(
            renderer.detail_panel(
                "approval",
                [renderer.flow_message("approval_gate", "approved", {"action": event.get("action_type", "action")})],
            )
        )
        return True
    gate.deny(request_id, reason="denied", approver="archon-cli")
    renderer.emit(
        renderer.detail_panel(
            "approval",
            [renderer.flow_message("approval_gate", "denied", {"action": event.get("action_type", "action")})],
        )
    )
    return False
