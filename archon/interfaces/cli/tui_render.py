"""Rendering helpers for the ARCHON terminal UI."""

from __future__ import annotations

import shutil
import sys
import textwrap
from typing import Any

_RESET = "\033[0m"
_DIM = "\033[2m"
_COLORS = {
    "orange": "\033[38;5;208m",
    "green": "\033[38;5;40m",
    "cyan": "\033[38;5;45m",
    "red": "\033[38;5;203m",
}


def supports_ansi() -> bool:
    """Return whether stdout is interactive enough for ANSI framing.

    Example:
        >>> isinstance(supports_ansi(), bool)
        True
    """

    stream = sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)())


def preview(text: str, limit: int = 88) -> str:
    """Return a single-line preview suitable for activity feed items.

    Example:
        >>> preview("hello world", limit=5)
        'he...'
    """

    single_line = " ".join(str(text or "").split())
    if len(single_line) <= limit:
        return single_line
    return single_line[: limit - 3].rstrip() + "..."


def render_screen(
    *,
    mode: str,
    context: dict[str, Any],
    transcript: list[dict[str, str]],
    history: list[dict[str, Any]],
    running: bool,
) -> str:
    """Render the full TUI frame as a text buffer.

    Example:
        >>> "ARCHON" in render_screen(
        ...     mode="auto",
        ...     context={},
        ...     transcript=[],
        ...     history=[],
        ...     running=False,
        ... )
        True
    """

    ansi = supports_ansi()
    width = max(72, min(112, shutil.get_terminal_size((112, 40)).columns - 2))
    sections: list[str] = []
    if ansi:
        sections.append("\033[2J\033[H")
    sections.append(_title_line("ARCHON agent shell", width=width, ansi=ansi))
    sections.append(
        _panel(
            "Session",
            [
                f"Mode: {mode}",
                f"Context keys: {', '.join(sorted(context)) if context else 'none'}",
                f"Completed runs: {len(history)}",
                f"Status: {'running' if running else 'idle'}",
            ],
            width=width,
            ansi=ansi,
        )
    )
    if not transcript:
        sections.append(
            _panel(
                "Wake ARCHON",
                [
                    "ARCHON just came online.",
                    "Type the goal you want solved and the agent swarm will respond here.",
                    "Use /mode debate for analysis, and /context "
                    '{"market":"India"} to pin session context.',
                ],
                width=width,
                ansi=ansi,
            )
        )
        sections.append(
            _panel(
                "Commands",
                [
                    "/help",
                    "/mode <debate>",
                    "/context <json-object>",
                    "/clear-context",
                    "/history",
                    "/reset",
                    "/quit",
                ],
                width=width,
                ansi=ansi,
            )
        )
    else:
        for message in _visible_transcript(transcript):
            sections.append(
                _panel(
                    message.get("title", "Message"),
                    message.get("body", ""),
                    width=width,
                    ansi=ansi,
                    tone=message.get("tone", "default"),
                )
            )
    sections.append(_status_line(mode, history, running, ansi=ansi))
    sections.append(_composer_line(ansi=ansi))
    return "\n".join(sections) + "\n"


def render_menu_screen(
    *,
    title: str,
    body: list[str],
    options: list[Any],
    selected_index: int,
) -> str:
    """Render a boxed launcher/setup menu screen.

    Example:
        >>> screen = render_menu_screen(
        ...     title="Menu",
        ...     body=["Choose one option."],
        ...     options=[type("O", (), {"label": "One", "description": "First"})()],
        ...     selected_index=0,
        ... )
        >>> "Choose one option." in screen
        True
    """

    ansi = supports_ansi()
    width = max(72, min(112, shutil.get_terminal_size((112, 40)).columns - 2))
    lines: list[str] = []
    if ansi:
        lines.append("\033[2J\033[H")
    lines.append(_title_line("ARCHON setup shell", width=width, ansi=ansi))
    lines.append(_panel(title, body, width=width, ansi=ansi, tone="system"))
    option_lines = []
    for index, option in enumerate(options, start=1):
        prefix = _paint("●", color="green", ansi=ansi) if index - 1 == selected_index else "○"
        option_lines.append(f"{prefix} {index}. {option.label}")
        option_lines.append(f"   {option.description}")
    lines.append(_panel("Options", option_lines, width=width, ansi=ansi, tone="assistant"))
    lines.append(
        _paint(
            "Use arrow keys + Enter, or type the option number if raw input is unavailable.",
            color="cyan",
            ansi=ansi,
            dim=True,
        )
    )
    return "\n".join(lines) + "\n"


def _visible_transcript(transcript: list[dict[str, str]]) -> list[dict[str, str]]:
    return transcript[-10:]


def _title_line(title: str, *, width: int, ansi: bool) -> str:
    marker = _paint("<>", color="green", ansi=ansi)
    label = _paint(title, color="orange", ansi=ansi)
    fill = "-" * max(1, width - len(title) - 6)
    return f"{marker} {label} {fill}"


def _status_line(
    mode: str,
    history: list[dict[str, Any]],
    running: bool,
    *,
    ansi: bool,
) -> str:
    status = "busy" if running else "idle"
    text = f"agent main | session main (archon-tui) | mode {mode} | runs {len(history)} | {status}"
    return _paint(text, color="cyan", ansi=ansi, dim=True)


def _composer_line(*, ansi: bool) -> str:
    return _paint("Input: type a goal or use /help", color="default", ansi=ansi, dim=True)


def _panel(
    title: str,
    body: str | list[str],
    *,
    width: int,
    ansi: bool,
    tone: str = "default",
) -> str:
    header = _panel_header(title, width=width, ansi=ansi, tone=tone)
    inner_width = width - 4
    if isinstance(body, list):
        raw_lines = body
    else:
        raw_lines = str(body).splitlines() or [""]
    content_lines: list[str] = []
    for raw_line in raw_lines:
        wrapped = textwrap.wrap(
            raw_line,
            width=max(10, inner_width),
            replace_whitespace=False,
            drop_whitespace=False,
        )
        content_lines.extend(wrapped or [""])
    lines = [header]
    for line in content_lines:
        lines.append(f"| {_pad(line, inner_width)} |")
    lines.append("+" + "-" * (width - 2) + "+")
    return "\n".join(lines)


def _panel_header(title: str, *, width: int, ansi: bool, tone: str) -> str:
    tone_color = {
        "assistant": "cyan",
        "user": "green",
        "event": "orange",
        "error": "red",
        "system": "orange",
        "default": "orange",
    }.get(tone, "orange")
    label = _paint(title, color=tone_color, ansi=ansi)
    fill = "-" * max(1, width - len(title) - 5)
    return f"+- {label} {fill}+"


def _pad(text: str, width: int) -> str:
    clean = str(text or "")
    if len(clean) >= width:
        return clean[:width]
    return clean + (" " * (width - len(clean)))


def _paint(text: str, *, color: str, ansi: bool, dim: bool = False) -> str:
    if not ansi:
        return text
    prefix = ""
    if dim:
        prefix += _DIM
    prefix += _COLORS.get(color, "")
    if not prefix:
        return text
    return f"{prefix}{text}{_RESET}"
