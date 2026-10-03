"""Pure planning rules, independent of command parsing and persistence."""

import datetime as dt


def calculate_start_by(
    estimate: int, deadline: dt.date, worked: int, work_per_day: int
) -> dt.date:
    if work_per_day <= 0:
        raise ValueError("work per day must be greater than zero")
    remaining = max(0, estimate - worked)
    if not remaining:
        return dt.date.today()
    days = (remaining + work_per_day - 1) // work_per_day
    return deadline - dt.timedelta(days=days)
