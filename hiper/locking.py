"""Cooperative, reentrant process locks for short persistence transactions."""

import fcntl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_held: ContextVar[frozenset[str]] = ContextVar("hiper_locks", default=frozenset())
_threads = threading.RLock()


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Serialize cooperating hiper writers; callers must keep transactions short."""
    name = str(path.resolve())
    with _threads:
        if name in _held.get():
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            token = _held.set(_held.get() | {name})
            try:
                yield
            finally:
                _held.reset(token)
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
