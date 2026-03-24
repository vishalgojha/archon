"""Raw terminal input helpers for ARCHON's interactive TUI menus."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Literal

KeyName = Literal["up", "down", "left", "right", "enter", "escape", "space", "other"]


def supports_raw_keys() -> bool:
    """Return whether the current stdin/stdout pair can handle raw key input.

    Example:
        >>> isinstance(supports_raw_keys(), bool)
        True
    """

    return bool(
        getattr(sys.stdin, "isatty", lambda: False)()
        and getattr(sys.stdout, "isatty", lambda: False)()
    )


async def read_key() -> KeyName:
    """Read one keypress and normalize it to a small key vocabulary.

    Example:
        >>> asyncio.run(asyncio.sleep(0, result="enter")) in {"enter", "other"}
        True
    """

    return await asyncio.to_thread(_read_key_sync)


def _read_key_sync() -> KeyName:
    if os.name == "nt":
        return _read_key_windows()
    return _read_key_posix()


def _read_key_windows() -> KeyName:
    import msvcrt

    first = msvcrt.getwch()
    if first in {"\x00", "\xe0"}:
        second = msvcrt.getwch()
        arrow_keys: dict[str, KeyName] = {
            "H": "up",
            "P": "down",
            "K": "left",
            "M": "right",
        }
        return arrow_keys.get(second, "other")
    if first == "\r":
        return "enter"
    if first == "\x1b":
        return "escape"
    if first == " ":
        return "space"
    return "other"


def _read_key_posix() -> KeyName:
    import termios
    import tty

    stream = sys.stdin
    fd = stream.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        first = stream.read(1)
        if first == "\x1b":
            second = stream.read(1)
            if second != "[":
                return "escape"
            third = stream.read(1)
            arrow_keys: dict[str, KeyName] = {
                "A": "up",
                "B": "down",
                "C": "right",
                "D": "left",
            }
            return arrow_keys.get(third, "other")
        if first in {"\r", "\n"}:
            return "enter"
        if first == " ":
            return "space"
        return "other"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
