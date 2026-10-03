"""Duration and local datetime conversions shared by commands and persistence."""

import datetime as dt
import re


def format_hms(seconds: int) -> str:
    if seconds < 0:
        raise ValueError("duration must be nonnegative")
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}h{minutes:02d}m{secs:02d}s"
    return f"{minutes:02d}m{secs:02d}s"


def parse_duration(value: str) -> int:
    """Parse h/m/s components; a unitless final number denotes minutes."""
    value = value.strip().lower()
    if not value or re.fullmatch(r"(?:[0-9]+[hms])*[0-9]*", value) is None:
        raise ValueError("duration must use nonnegative numbers with h, m, or s units")
    units = {"h": 3600, "m": 60, "s": 1, "": 60}
    return sum(
        int(number) * units[unit]
        for number, unit in re.findall(r"([0-9]+)([hms]?)", value)
    )


def local_datetime(value: str) -> dt.datetime:
    """Normalize ISO offsets to local wall time, matching historical naive CSVs."""
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        return parsed.astimezone().replace(tzinfo=None)
    return parsed
