"""POSIX terminal input boundary. Saved attributes are opaque termios values."""

import os
import select
import sys
import termios
import tty
from typing import Any

TerminalSettings = list[Any]


def _read_key_nonblocking(timeout_s: float = 0.0) -> str | None:
    rlist, _, _ = select.select([sys.stdin], [], [], timeout_s)
    if not rlist:
        return None
    ch = os.read(sys.stdin.fileno(), 1)
    if not ch:
        raise EOFError
    return ch.decode(errors="ignore")


def _set_raw_mode() -> tuple[int, TerminalSettings]:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    return fd, old_settings


def _restore_mode(fd: int | None, old_settings: TerminalSettings | None) -> None:
    if fd is not None and old_settings is not None:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
