"""Typed TUI workflows independent of widgets and event handling."""

import datetime as dt
from dataclasses import dataclass, field

from .. import config, storage
from ..defaults import DEFAULT_WORK_PER_DAY
from ..habits import match_habit, parse_frequency
from ..models import Book, Goal, Habit, LogEntry, Session
from ..planning import calculate_start_by
from ..session import SessionClock
from ..timeutil import format_hms, parse_duration


@dataclass(frozen=True, slots=True)
class Snapshot:
    sessions: list[Session]
    goals: list[Goal]
    books: list[Book]
    habits: list[Habit]
    logs: list[LogEntry]
    data_dir: str

    @property
    def today_seconds(self) -> int:
        today = dt.date.today()
        return sum(s["duration"] for s in self.sessions if s["start"].date() == today)


def load_snapshot() -> Snapshot:
    goals = storage.load_goals_csv()
    for goal in goals:
        deadline = goal["deadline"]
        if deadline is not None and goal["estimate_seconds"] > 0:
            work_per_day = parse_duration(
                config.get_config("work_per_day", DEFAULT_WORK_PER_DAY)
            )
            goal["start_by"] = calculate_start_by(
                goal["estimate_seconds"],
                deadline,
                goal["time_worked_seconds"],
                work_per_day,
            )
    return Snapshot(
        storage.load_sessions_csv(),
        goals,
        storage.load_read_csv(),
        storage.load_habits_csv(),
        storage.load_log_csv(),
        storage.get_data_dir(),
    )


@dataclass(slots=True)
class FocusSession:
    title: str
    comment: str = ""
    target: int | None = None
    started: dt.datetime = field(default_factory=dt.datetime.now)
    clock: SessionClock = field(default_factory=SessionClock)
    paused: bool = False

    def toggle_pause(self) -> None:
        if self.paused:
            self.clock.resume()
        else:
            self.clock.pause()
        self.paused = not self.paused

    def save(self) -> str:
        # Failed writes keep the paused session available for retry.
        self.clock.pause()
        self.paused = True
        seconds = self.clock.seconds
        storage.save_session_csv(
            self.title, self.started, dt.datetime.now(), seconds, self.comment
        )
        return f"Saved {self.title or 'session'} · {format_hms(seconds)}"


def create_focus(title: str, comment: str, target: str) -> FocusSession:
    seconds = parse_duration(target) if target.strip() else None
    if seconds is not None and seconds <= 0:
        raise ValueError("focus target must be greater than zero")
    return FocusSession(title.strip(), comment.strip(), seconds)


def _title(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("title cannot be empty")
    return value


def save_goal(title: str, estimate: str, deadline: str) -> str:
    title = _title(title)
    seconds = parse_duration(estimate)
    if seconds <= 0:
        raise ValueError("estimate must be greater than zero")
    due = dt.date.fromisoformat(deadline.strip()) if deadline.strip() else None
    work_per_day = parse_duration(
        config.get_config("work_per_day", DEFAULT_WORK_PER_DAY)
    )
    start_by = calculate_start_by(seconds, due, 0, work_per_day) if due else None
    with storage.data_transaction():
        goals = storage.load_goals_csv()
        existing = next((goal for goal in goals if goal["title"] == title), None)
        goal = Goal(
            title=title,
            estimate_seconds=seconds,
            estimate_formatted=format_hms(seconds),
            estimate_timestamp=dt.datetime.now(),
            deadline=due,
            time_worked_seconds=0,
            time_worked_formatted="",
            start_by=start_by,
        )
        if existing is not None:
            goals[goals.index(existing)] = goal
        else:
            goals.append(goal)
        storage.save_goals_csv(goals)
    return f"Saved estimate for {title}"


def finish_goal(title: str) -> str:
    with storage.data_transaction():
        goals = storage.load_goals_csv()
        goal = next((goal for goal in goals if goal["title"] == title), None)
        if goal is None:
            raise ValueError("select an existing goal")
        goal.update(
            estimate_seconds=0,
            estimate_formatted="",
            estimate_timestamp=None,
            deadline=None,
            start_by=None,
        )
        storage.save_goals_csv(goals)
    return f"Finished {title}"


def add_book(title: str, length: str) -> str:
    title = _title(title)
    pages = int(length)
    if pages <= 0:
        raise ValueError("book length must be greater than zero")
    with storage.data_transaction():
        books = storage.load_read_csv()
        if any(book["title"] == title for book in books):
            raise ValueError("a book with this title already exists")
        books.append(
            Book(title=title, length=pages, current_page=0, time_per_page_seconds=0)
        )
        storage.save_read_csv(books)
    return f"Added {title}"


def update_book(title: str, page: str, time_per_page: str) -> str:
    position = int(page)
    seconds = parse_duration(time_per_page) if time_per_page.strip() else None
    with storage.data_transaction():
        books = storage.load_read_csv()
        book = next((book for book in books if book["title"] == title), None)
        if book is None:
            raise ValueError("select an existing book")
        if not 0 <= position <= book["length"]:
            raise ValueError(f"page must be between 0 and {book['length']}")
        book["current_page"] = position
        if seconds is not None:
            book["time_per_page_seconds"] = seconds
        storage.save_read_csv(books)
    return f"Updated {title} to page {position}"


def add_habit(title: str, frequency: str) -> str:
    title = _title(title)
    frequency = frequency.strip().lower()
    parse_frequency(frequency)
    with storage.data_transaction():
        habits = storage.load_habits_csv()
        if any(habit["name"] == title for habit in habits):
            raise ValueError("a habit with this title already exists")
        habits.append(
            Habit(name=title, frequency=frequency, created_at=dt.datetime.now())
        )
        storage.save_habits_csv(habits)
    return f"Added {title}"


def habit_done_today(title: str, logs: list[LogEntry]) -> bool:
    today = dt.date.today()
    return any(
        log["timestamp"] is not None
        and log["timestamp"].date() == today
        and match_habit(log["message"], title) is not None
        for log in logs
    )


def complete_habit(title: str) -> str:
    with storage.data_transaction():
        if not any(habit["name"] == title for habit in storage.load_habits_csv()):
            raise ValueError("select an existing habit")
        if habit_done_today(title, storage.load_log_csv()):
            return f"{title} is already done today"
        storage.append_log_csv(title)
    return f"Marked {title} done today"


def add_log(message: str) -> str:
    message = message.strip()
    if not message:
        raise ValueError("log message cannot be empty")
    storage.append_log_csv(message)
    return "Added log entry"
