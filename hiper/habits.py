"""Habit scheduling and matching rules shared by terminal interfaces."""

import datetime as dt


def parse_frequency(frequency: str) -> set[str]:
    """Parse frequency string and return set of day abbreviations.
    'daily' returns all days, otherwise parses comma-separated days like 'mon,tue,sat'.
    """
    freq = frequency.strip().lower()
    if freq == "daily":
        return {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    days: set[str] = set()
    day_map: dict[str, str] = {
        "mon": "mon",
        "monday": "mon",
        "tue": "tue",
        "tuesday": "tue",
        "wed": "wed",
        "wednesday": "wed",
        "thu": "thu",
        "thursday": "thu",
        "fri": "fri",
        "friday": "fri",
        "sat": "sat",
        "saturday": "sat",
        "sun": "sun",
        "sunday": "sun",
    }
    for day_str in freq.split(","):
        day_str = day_str.strip().lower()
        if day_str not in day_map:
            raise ValueError(f"invalid habit frequency: {day_str!r}")
        days.add(day_map[day_str])
    return days


def today_day_abbr() -> str:
    """Get today's day abbreviation (mon, tue, wed, etc.)."""
    today = dt.date.today()
    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    return day_names[today.weekday()]


def day_abbr(date: dt.date) -> str:
    """Get day abbreviation for a given date (mon, tue, wed, etc.)."""
    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    return day_names[date.weekday()]


def is_scheduled_today(frequency: str) -> bool:
    """Check if a habit is scheduled for today based on its frequency."""
    scheduled_days = parse_frequency(frequency)
    today_abbr = today_day_abbr()
    return today_abbr in scheduled_days


def match_habit(log_message: str, habit_name: str) -> str | None:
    """Check if a log message matches a habit."""
    log_message = log_message.strip()
    habit_name = habit_name.strip()
    if log_message == habit_name:
        return ""
    if log_message.startswith(habit_name + ":"):
        param = log_message[len(habit_name) + 1 :].strip()
        if param:
            first_word = param.split()[0] if param else ""
            return first_word if first_word else None
    return None
