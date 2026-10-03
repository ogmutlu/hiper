"""Exercise the real terminal lifecycle using a pseudo-terminal."""

import os
import select
import signal
import subprocess
import sys
import termios
import time
import unittest
from collections.abc import Iterator
from contextlib import contextmanager

from hiper import storage
from tests.test_regressions import isolated


@contextmanager
def terminal_process(*args: str) -> Iterator[tuple[subprocess.Popen[bytes], int, int]]:
    master, slave = os.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "hiper", "fokus", *args],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    try:
        yield process, master, slave
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        os.close(master)
        os.close(slave)


def wait_for(master: int, text: bytes) -> bytes:
    output = b""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        ready, _, _ = select.select(
            [master], [], [], max(0, deadline - time.monotonic())
        )
        if ready:
            output += os.read(master, 65536)
            if text in output:
                return output
    raise AssertionError(f"terminal did not print {text!r}: {output!r}")


class FocusIntegrationTests(unittest.TestCase):
    def test_pause_save_restores_terminal_and_writes_comment(self) -> None:
        with (
            isolated(),
            terminal_process("--title", "task", "--comment", "note") as (
                process,
                master,
                slave,
            ),
        ):
            # ECHO and ICANON should be restored after saving.
            wait_for(master, b":>")
            os.write(master, b" ")
            wait_for(master, b":> ")
            os.write(master, b"s\n")
            wait_for(master, b"Saved session:")
            self.assertEqual(process.wait(timeout=5), 0)
            attributes = termios.tcgetattr(slave)
            self.assertTrue(attributes[3] & termios.ECHO)
            self.assertTrue(attributes[3] & termios.ICANON)
            sessions = storage.load_sessions_csv()
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["title"], "task")
            self.assertEqual(sessions[0]["comment"], "note")

    def test_pause_discard_leaves_no_session(self) -> None:
        with isolated(), terminal_process() as (process, master, slave):
            wait_for(master, b":>")
            os.write(master, b" ")
            wait_for(master, b":> ")
            os.write(master, b"d\n")
            wait_for(master, b"Session cancelled")
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertTrue(termios.tcgetattr(slave)[3] & termios.ICANON)
            self.assertEqual(storage.load_sessions_csv(), [])

    def test_interrupt_restores_terminal_and_returns_130(self) -> None:
        with isolated(), terminal_process() as (process, master, slave):
            wait_for(master, b":>")
            process.send_signal(signal.SIGINT)
            wait_for(master, b"Interrupted.")
            self.assertEqual(process.wait(timeout=5), 130)
            self.assertTrue(termios.tcgetattr(slave)[3] & termios.ECHO)
            self.assertTrue(termios.tcgetattr(slave)[3] & termios.ICANON)
