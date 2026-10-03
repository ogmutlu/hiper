"""Atomic replacement for configuration and CSV snapshots."""

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO


@contextmanager
def atomic_text_writer(
    path: str | Path, *, newline: str | None = None
) -> Iterator[TextIO]:
    """Replace a file only after the complete new contents reach disk.

    A failed serialization leaves the original file intact. The temporary file
    lives beside the destination so replacement stays on the same filesystem.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        if destination.exists():
            os.chmod(temporary, destination.stat().st_mode & 0o777)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
