"""Tests for raw TUI key normalization helpers."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from archon.interfaces.cli import tui_input


class _TTYState:
    def __init__(self, *, stdin: bool, stdout: bool) -> None:
        self.stdin = SimpleNamespace(isatty=lambda: stdin)
        self.stdout = SimpleNamespace(isatty=lambda: stdout)


class _FakePosixStream:
    def __init__(self, chars: list[str]) -> None:
        self._chars = iter(chars)

    def fileno(self) -> int:
        return 7

    def read(self, _count: int) -> str:
        return next(self._chars)


def test_supports_raw_keys_requires_tty_on_stdin_and_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _TTYState(stdin=True, stdout=True)
    monkeypatch.setattr(tui_input.sys, "stdin", state.stdin)
    monkeypatch.setattr(tui_input.sys, "stdout", state.stdout)
    assert tui_input.supports_raw_keys() is True

    state = _TTYState(stdin=True, stdout=False)
    monkeypatch.setattr(tui_input.sys, "stdin", state.stdin)
    monkeypatch.setattr(tui_input.sys, "stdout", state.stdout)
    assert tui_input.supports_raw_keys() is False


@pytest.mark.asyncio
async def test_read_key_uses_asyncio_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_to_thread(func):  # type: ignore[no-untyped-def]
        assert func is tui_input._read_key_sync
        return "enter"

    monkeypatch.setattr(tui_input.asyncio, "to_thread", fake_to_thread)

    assert await tui_input.read_key() == "enter"


def test_read_key_sync_dispatches_by_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tui_input.os, "name", "nt")
    monkeypatch.setattr(tui_input, "_read_key_windows", lambda: "up")
    monkeypatch.setattr(tui_input, "_read_key_posix", lambda: "down")
    assert tui_input._read_key_sync() == "up"

    monkeypatch.setattr(tui_input.os, "name", "posix")
    assert tui_input._read_key_sync() == "down"


@pytest.mark.parametrize(
    ("chars", "expected"),
    [
        (["\x00", "H"], "up"),
        (["\xe0", "P"], "down"),
        (["\r"], "enter"),
        (["\x1b"], "escape"),
        ([" "], "space"),
        (["x"], "other"),
    ],
)
def test_read_key_windows_normalizes_sequences(
    monkeypatch: pytest.MonkeyPatch,
    chars: list[str],
    expected: str,
) -> None:
    values = iter(chars)
    fake_msvcrt = SimpleNamespace(getwch=lambda: next(values))
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    assert tui_input._read_key_windows() == expected


@pytest.mark.parametrize(
    ("chars", "expected"),
    [
        (["\x1b", "[", "A"], "up"),
        (["\x1b", "[", "B"], "down"),
        (["\x1b", "x"], "escape"),
        (["\n"], "enter"),
        ([" "], "space"),
        (["x"], "other"),
    ],
)
def test_read_key_posix_normalizes_sequences_and_restores_terminal(
    monkeypatch: pytest.MonkeyPatch,
    chars: list[str],
    expected: str,
) -> None:
    calls: dict[str, object] = {}
    old_settings = object()

    def tcgetattr(fd: int) -> object:
        calls["tcgetattr_fd"] = fd
        return old_settings

    fake_termios = SimpleNamespace(
        TCSADRAIN=99,
        tcgetattr=tcgetattr,
        tcsetattr=lambda fd, when, value: calls.update({"tcsetattr": (fd, when, value)}),
    )

    def setraw(fd: int) -> None:
        calls["setraw_fd"] = fd

    monkeypatch.setitem(sys.modules, "termios", fake_termios)
    monkeypatch.setitem(sys.modules, "tty", SimpleNamespace(setraw=setraw))
    monkeypatch.setattr(tui_input.sys, "stdin", _FakePosixStream(chars))

    assert tui_input._read_key_posix() == expected
    assert calls["tcgetattr_fd"] == 7
    assert calls["setraw_fd"] == 7
    assert calls["tcsetattr"] == (7, 99, old_settings)
