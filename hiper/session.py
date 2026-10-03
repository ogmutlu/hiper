"""Focus timing independent of terminal IO and wall-clock changes."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(slots=True)
class SessionClock:
    now: Callable[[], float] = time.monotonic
    _accumulated: float = field(default=0.0, init=False)
    _started: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.resume()

    @property
    def seconds(self) -> int:
        running = self.now() - self._started if self._started is not None else 0.0
        return int(self._accumulated + max(0.0, running))

    def pause(self) -> None:
        if self._started is not None:
            self._accumulated += max(0.0, self.now() - self._started)
            self._started = None

    def resume(self) -> None:
        if self._started is None:
            self._started = self.now()
