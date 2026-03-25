from __future__ import annotations

import os
from string import Formatter
from typing import Any

from archon.cli.copy import COMMAND_COPY, DRAWER_COPY, FLOW_COPY

try:  # pragma: no cover - optional dependency
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except Exception:  # pragma: no cover - optional dependency
    Console = None
    Group = None
    Panel = None
    Table = None
    Text = None


def _rich_enabled() -> bool:
    return not os.environ.get("PYTEST_CURRENT_TEST")


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _format_text(template: str, values: dict[str, Any]) -> str:
    return str(template).format_map(_SafeFormatDict(values))


def _has_field(template: str, field_name: str) -> bool:
    for _, field, _, _ in Formatter().parse(str(template)):
        if field == field_name:
            return True
    return False


def _as_panel(title: str, lines: list[str], *, subtitle: str | None = None) -> Any:
    body = "\n".join(line for line in lines if line)
    if Panel is None or not _rich_enabled():
        if subtitle:
            return "\n".join([title, subtitle, body]).strip()
        return "\n".join([title, body]).strip()
    if Text is None:
        return Panel(body, title=title, subtitle=subtitle)
    text = Text()
    for index, line in enumerate(lines):
        if index:
            text.append("\n")
        text.append(line)
    return Panel(text, title=title, subtitle=subtitle)


def banner() -> Any:
    title = "ARCHON"
    if Panel is None or not _rich_enabled():
        return title
    return Panel(title, title=title)


def emit(renderable: Any) -> None:
    if (
        Console is not None
        and not isinstance(renderable, str)
        and not os.environ.get("PYTEST_CURRENT_TEST")
    ):
        Console().print(renderable)
        return
    print(str(renderable))


def detail_panel(title: str, lines: list[str]) -> Any:
    return _as_panel(title, lines)


def drawer_panel(drawer_id: str) -> Any:
    drawer = DRAWER_COPY[drawer_id]
    availability = str(drawer.get("availability", "live")).strip().lower()
    status_lines = {
        "live": "Status: live. Commands in this drawer execute today.",
        "partial": "Status: partial. Some commands execute today; placeholder commands say not implemented yet.",
        "staged": "Status: staged. Commands are visible, but they do not execute runtime work yet.",
    }
    lines = [
        f"{drawer['icon']} {drawer['title']}",
        drawer["tagline"],
        "",
        status_lines.get(availability, status_lines["live"]),
        "",
        drawer["explanation"],
        "",
    ]
    for command_id, description in drawer["commands"].items():
        lines.append(f"{command_id.split('.', 1)[1]}  {description}")
    lines.append("")
    lines.append("Try now:")
    for command_id in drawer["commands"]:
        lines.append(f"- archon {command_id.replace('.', ' ', 1)}")
    if drawer["requires"]:
        lines.append("")
        for item in drawer["requires"]:
            lines.append(f"[ ] {item}")
    first_command = next(iter(drawer["commands"])).split(".", 1)[1]
    return _as_panel(
        drawer["title"],
        lines,
        subtitle=f"archon {drawer_id} {first_command}",
    )


def what_panel(command_id: str) -> Any:
    return _as_panel(command_id, [str(COMMAND_COPY[command_id]["what"])])


def step_row(label: str, state: str) -> Any:
    symbol = {
        "pending": "[ ]",
        "running": "[>]",
        "success": "[x]",
        "error": "[!]",
    }.get(state, "[ ]")
    return f"{symbol} {label}"


def result_panel(command_id: str, data: dict[str, Any]) -> Any:
    result_map = COMMAND_COPY[command_id]["results"]
    result_key = str(data.get("result_key", "success"))
    template = str(result_map.get(result_key) or result_map.get("success") or "")
    return _as_panel(command_id, [_format_text(template, data)])


def next_steps_panel(command_id: str) -> Any:
    lines = [f"- {item}" for item in COMMAND_COPY[command_id]["next_steps"]]
    return _as_panel(command_id, lines)


def live_task_panel(state: dict[str, Any]) -> Any:
    copy = FLOW_COPY["live_task"]
    lines = [
        f"{copy['status_label']}: {state.get('status', copy['idle'])}",
        f"{copy['mode_label']}: {state.get('mode', '-')}",
        f"{copy['agent_label']}: {state.get('agent', '-')}",
        f"{copy['round_label']}: {state.get('round', '-')}",
        f"{copy['cost_label']}: {state.get('cost', '-')}",
        f"{copy['event_label']}: {state.get('event', copy['idle'])}",
    ]
    return _as_panel(copy["title"], lines)


def approval_panel(data: dict[str, Any]) -> Any:
    copy = FLOW_COPY["approval_gate"]
    lines = [_format_text(copy["body"], data)]
    countdown = str(data.get("countdown", ""))
    if countdown:
        lines.append(_format_text(copy["countdown"], {"seconds": countdown}))
    return _as_panel(copy["title"], lines)


def placeholder_panel(command_id: str) -> Any:
    copy = FLOW_COPY["placeholder"]
    module = command_id.split(".", 1)[0]
    data = {"command": command_id, "module": module}
    lines = [
        _format_text(copy["body"], data),
        _format_text(copy["detail"], data),
        "",
        "There are no flags or inputs to provide yet because execution is not wired.",
        "",
        _format_text(copy["next"], data),
    ]
    return _as_panel(copy["title"], lines)


def steps_table(command_id: str, states: list[str]) -> Any:
    steps = COMMAND_COPY[command_id]["steps"]
    lines = [step_row(label, states[index]) for index, label in enumerate(steps)]
    if Table is None or Panel is None or Group is None or not _rich_enabled():
        return _as_panel(command_id, lines)
    table = Table.grid(padding=(0, 1))
    table.add_column()
    for line in lines:
        table.add_row(line)
    return Panel(Group(table), title=command_id)


def flow_message(flow_id: str, key: str, values: dict[str, Any] | None = None) -> str:
    values = values or {}
    text = str(FLOW_COPY[flow_id][key])
    if values and any(_has_field(text, field) for field in values):
        return _format_text(text, values)
    return text
