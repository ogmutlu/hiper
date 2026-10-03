"""CSV persistence with typed records, runtime paths, and atomic updates.

Reads never create or rewrite files. Goals derive their worked time from sessions;
only explicit mutations persist the resulting snapshot. Historical CSVs retain
support for missing optional columns.
"""

import csv
import datetime as dt
import hashlib
import json
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from functools import wraps
from pathlib import Path
from uuid import uuid4

from . import config
from .files import atomic_text_writer
from .locking import file_lock
from .models import Book, Goal, Habit, LogEntry, Session
from .timeutil import format_hms, local_datetime, parse_duration

__all__ = [
    "data_transaction",
    "format_hms",
    "parse_duration",
    "get_data_dir",
    "save_session_csv",
    "load_sessions_csv",
    "load_goals_csv",
    "save_goals_csv",
    "get_time_worked_for_title",
    "get_time_worked_today",
    "load_read_csv",
    "save_read_csv",
    "append_log_csv",
    "load_log_csv",
    "load_habits_csv",
    "save_habits_csv",
    "get_online_dir",
    "append_online_fokus_line",
    "get_other_online_fokus_status",
]

SESSION_FIELDS = (
    "id",
    "title",
    "start",
    "end",
    "duration",
    "duration_formatted",
    "comment",
)
GOAL_FIELDS = (
    "title",
    "estimate_seconds",
    "estimate_formatted",
    "estimate_timestamp",
    "deadline",
    "time_worked_seconds",
    "time_worked_formatted",
    "start_by",
)
BOOK_FIELDS = ("title", "length", "current_page", "time_per_page_seconds")
HABIT_FIELDS = ("name", "frequency", "created_at")
LOG_FIELDS = ("message", "timestamp", "id")
LOG_REQUIRED = ("message", "timestamp")


def get_data_dir() -> str:
    return config.get_data_dir()


def _path(name: str) -> Path:
    return Path(get_data_dir()) / name


def data_transaction() -> AbstractContextManager[None]:
    return file_lock(_path(".hiper.lock"))


def _locked[**P, T](function: Callable[P, T]) -> Callable[P, T]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        with file_lock(_path(".hiper.lock")):
            return function(*args, **kwargs)

    return wrapped


def _rows(name: str, required: Sequence[str]) -> Iterator[dict[str, str]]:
    path = _path(name)
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if not set(required).issubset(fields) or len(fields) != len(set(fields)):
            raise ValueError(
                f"{path}: invalid CSV header; required columns: {', '.join(required)}"
            )
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path}:{reader.line_num}: malformed CSV row")
            yield {
                key: value
                for key, value in row.items()
                if key is not None and value is not None
            }


def _write(
    name: str, fields: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    path = _path(name)
    with atomic_text_writer(path, newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def _identified_rows(name: str, required: Sequence[str]) -> list[dict[str, str]]:
    rows = list(_rows(name, required))
    occurrences: dict[str, int] = {}
    identifiers: set[str] = set()
    for row in rows:
        digest = hashlib.sha256(
            json.dumps(
                {key: value for key, value in row.items() if key != "id"},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        occurrence = occurrences.get(digest, 0)
        occurrences[digest] = occurrence + 1
        identifier = row.get("id") or f"legacy-{digest}-{occurrence}"
        if identifier in identifiers:
            raise ValueError(f"{name}: duplicate record ID")
        identifiers.add(identifier)
        row["id"] = identifier
    return rows


def _preserved_fields(name: str, required: Sequence[str]) -> list[str]:
    path = _path(name)
    fields = list(required)
    if path.exists() and path.stat().st_size:
        with path.open(newline="", encoding="utf-8") as stream:
            fields = list(csv.DictReader(stream).fieldnames or required)
    return fields + [field for field in required if field not in fields]


def _integer(row: Mapping[str, str], field: str) -> int:
    value = int(row.get(field, "") or 0)
    if value < 0:
        raise ValueError(f"{field} must be nonnegative")
    return value


def load_sessions_csv() -> list[Session]:
    sessions: list[Session] = []
    for row in _identified_rows("sessions.csv", ("title", "start", "end", "duration")):
        start = local_datetime(row["start"])
        end = local_datetime(row["end"])
        duration = _integer(row, "duration")
        if end < start:
            raise ValueError("sessions.csv: end precedes start")
        sessions.append(
            Session(
                id=row["id"],
                title=row["title"],
                start=start,
                end=end,
                duration=duration,
                comment=row.get("comment", ""),
            )
        )
    return sessions


@_locked
def save_session_csv(
    title: str,
    start: dt.datetime,
    end: dt.datetime,
    duration_seconds: int,
    comment: str = "",
) -> str:
    start = local_datetime(start.isoformat())
    end = local_datetime(end.isoformat())
    if duration_seconds < 0 or end < start:
        raise ValueError(
            "session must have a nonnegative duration and end on or after start"
        )
    # Preserve additional user columns and accept reordered headers when appending.
    path = _path("sessions.csv")
    rows = _identified_rows("sessions.csv", ("title", "start", "end", "duration"))
    fields = list(SESSION_FIELDS)
    if path.exists() and path.stat().st_size:
        with path.open(newline="", encoding="utf-8") as stream:
            fields = list(csv.DictReader(stream).fieldnames or SESSION_FIELDS)
        if "comment" not in fields:
            fields.append("comment")
    rows.append(
        {
            "id": uuid4().hex,
            "title": title.strip(),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "duration": str(duration_seconds),
            "duration_formatted": format_hms(duration_seconds),
            "comment": comment,
        }
    )
    # Old hand-written CSVs may lack the derived duration column.
    for field in SESSION_FIELDS:
        if field not in fields:
            fields.append(field)
    result = _write("sessions.csv", fields, rows)
    try:
        save_goals_csv(load_goals_csv())
    except (OSError, ValueError) as exc:
        print(
            f"Warning: session saved, but goals could not be refreshed: {exc}",
            file=sys.stderr,
        )
    return result


def get_time_worked_for_title(
    title: str, after_timestamp: dt.datetime | None = None
) -> int:
    return _worked(load_sessions_csv(), title.strip(), after_timestamp)


def _worked(sessions: Sequence[Session], title: str, after: dt.datetime | None) -> int:
    if after is not None:
        after = local_datetime(after.isoformat())
    return sum(
        row["duration"]
        for row in sessions
        if row["title"].strip() == title and (after is None or row["start"] >= after)
    )


def get_time_worked_today() -> int:
    today = dt.date.today()
    return sum(
        row["duration"] for row in load_sessions_csv() if row["start"].date() == today
    )


def load_goals_csv() -> list[Goal]:
    goals: dict[str, Goal] = {}
    deleted: set[str] = set()
    for row in _rows("goals.csv", ("title", "estimate_seconds")):
        title = row["title"].strip()
        if row.get("deleted") == "1":
            deleted.add(title)
            continue
        if not title:
            raise ValueError("goals.csv: title cannot be empty")
        if title in goals:
            raise ValueError(f"goals.csv: duplicate title {title!r}")
        estimate = _integer(row, "estimate_seconds")
        timestamp = row.get("estimate_timestamp", "")
        deadline = row.get("deadline", "")
        start_by = row.get("start_by", "")
        goals[title] = Goal(
            title=title,
            estimate_seconds=estimate,
            estimate_formatted=format_hms(estimate) if estimate else "",
            estimate_timestamp=local_datetime(timestamp) if timestamp else None,
            deadline=dt.date.fromisoformat(deadline) if deadline else None,
            time_worked_seconds=0,
            time_worked_formatted="",
            start_by=dt.date.fromisoformat(start_by) if start_by else None,
        )
    sessions = load_sessions_csv()
    for title in sorted({row["title"].strip() for row in sessions} - {""}):
        if title not in goals and title not in deleted:
            goals[title] = Goal(
                title=title,
                estimate_seconds=0,
                estimate_formatted="",
                estimate_timestamp=None,
                deadline=None,
                time_worked_seconds=0,
                time_worked_formatted="",
                start_by=None,
            )
    for goal in goals.values():
        worked = _worked(sessions, goal["title"], goal["estimate_timestamp"])
        goal["time_worked_seconds"] = worked
        goal["time_worked_formatted"] = format_hms(worked) if worked else ""
    return list(goals.values())


@_locked
def save_goals_csv(goals: list[Goal]) -> str:
    rows: list[dict[str, object]] = []
    for goal in goals:
        estimate = goal["estimate_seconds"]
        worked = goal["time_worked_seconds"]
        rows.append(
            {
                "title": goal["title"],
                "estimate_seconds": estimate,
                "estimate_formatted": format_hms(estimate) if estimate else "",
                "estimate_timestamp": goal["estimate_timestamp"].isoformat()
                if goal["estimate_timestamp"]
                else "",
                "deadline": goal["deadline"].isoformat() if goal["deadline"] else "",
                "time_worked_seconds": worked,
                "time_worked_formatted": format_hms(worked) if worked else "",
                "start_by": goal["start_by"].isoformat() if goal["start_by"] else "",
            }
        )
    active = {goal["title"] for goal in goals}
    for old in _rows("goals.csv", ("title", "estimate_seconds")):
        if old.get("deleted") == "1" and old["title"] not in active:
            rows.append(
                {field: old.get(field, "") for field in (*GOAL_FIELDS, "deleted")}
            )
    return _write("goals.csv", (*GOAL_FIELDS, "deleted"), rows)


def load_read_csv() -> list[Book]:
    books: list[Book] = []
    for row in _rows("read.csv", ("title", "length", "current_page")):
        book = Book(
            title=row["title"].strip(),
            length=_integer(row, "length"),
            current_page=_integer(row, "current_page"),
            time_per_page_seconds=_integer(row, "time_per_page_seconds"),
        )
        if (
            not book["title"]
            or book["length"] <= 0
            or book["current_page"] > book["length"]
        ):
            raise ValueError("read.csv: invalid book title, length, or current page")
        if any(item["title"] == book["title"] for item in books):
            raise ValueError(f"read.csv: duplicate title {book['title']!r}")
        books.append(book)
    return books


@_locked
def save_read_csv(reads: list[Book]) -> str:
    return _write("read.csv", BOOK_FIELDS, reads)


@_locked
def append_log_csv(message: str, when: dt.datetime | None = None) -> str:
    rows = _identified_rows("log.csv", LOG_REQUIRED)
    rows.append(
        {
            "id": uuid4().hex,
            "message": message,
            "timestamp": (when or dt.datetime.now()).isoformat(),
        }
    )
    return _write("log.csv", _preserved_fields("log.csv", LOG_FIELDS), rows)


def load_log_csv() -> list[LogEntry]:
    return [
        LogEntry(
            id=row["id"],
            message=row["message"],
            timestamp=local_datetime(row["timestamp"]) if row["timestamp"] else None,
        )
        for row in _identified_rows("log.csv", LOG_REQUIRED)
    ]


def load_habits_csv() -> list[Habit]:
    habits: list[Habit] = []
    path = _path("habits.csv")
    # Missing historical timestamps use file modification time, never today's date.
    fallback = (
        dt.datetime.fromtimestamp(path.stat().st_mtime)
        if path.exists()
        else dt.datetime.now()
    )
    for row in _rows("habits.csv", ("name", "frequency")):
        name = row["name"].strip()
        if not name:
            raise ValueError("habits.csv: name cannot be empty")
        timestamp = row.get("created_at", "")
        habits.append(
            Habit(
                name=name,
                frequency=row["frequency"],
                created_at=local_datetime(timestamp) if timestamp else fallback,
            )
        )
    return habits


@_locked
def save_habits_csv(habits: list[Habit]) -> str:
    return _write(
        "habits.csv",
        HABIT_FIELDS,
        [
            {
                "name": h["name"],
                "frequency": h["frequency"],
                "created_at": h["created_at"].isoformat(),
            }
            for h in habits
        ],
    )


def get_online_dir() -> str:
    return str(_path("online"))


def _sanitize_nickname_for_filename(nickname: str) -> str:
    value = nickname.strip()
    for character in '/\\:*?"<>|\r\n':
        value = value.replace(character, "_")
    return value or "unknown"


@_locked
def append_online_fokus_line(nickname: str, line: str) -> None:
    path = Path(get_online_dir()) / (_sanitize_nickname_for_filename(nickname) + ".txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line.replace("\n", " ").replace("\r", " ") + "\n")


def get_other_online_fokus_status(
    current_nickname: str,
) -> tuple[str, str, bool] | None:
    directory = Path(get_online_dir())
    if not directory.is_dir():
        return None
    current = _sanitize_nickname_for_filename(current_nickname)
    for path in sorted(directory.glob("*.txt")):
        if path.stem == current or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        lines = [line.strip() for line in lines if line.strip()]
        for line in reversed(lines):
            if line.startswith("fokus:"):
                return path.stem, line[6:].strip(), lines[-1].startswith("fokus:")
    return None


@_locked
def delete_record(kind: str, key: str) -> str:
    """Remove exactly one selected record, preserving unrelated history.

    Goal tombstones suppress implicit goals derived from historical sessions.
    Explicitly saving a new goal with the same title restores it.
    """
    if kind == "goal":
        goals = load_goals_csv()
        goal = next((goal for goal in goals if goal["title"] == key), None)
        if goal is None:
            raise ValueError(f"Goal not found: {key}")
        # Persist implicit goals before marking this one deleted.
        save_goals_csv(goals)
        rows = list(_rows("goals.csv", ("title", "estimate_seconds")))
        for row in rows:
            if row["title"] == key:
                row["deleted"] = "1"
        _write(
            "goals.csv", _preserved_fields("goals.csv", (*GOAL_FIELDS, "deleted")), rows
        )
    else:
        specifications = {
            "book": ("read.csv", "title", BOOK_FIELDS),
            "habit": ("habits.csv", "name", ("name", "frequency")),
            "session": ("sessions.csv", "id", ("title", "start", "end", "duration")),
            "log": ("log.csv", "id", LOG_REQUIRED),
        }
        if kind not in specifications:
            raise ValueError(f"Unknown record type: {kind}")
        name, field, required = specifications[kind]
        rows = (
            _identified_rows(name, required)
            if field == "id"
            else list(_rows(name, required))
        )
        matches = [row for row in rows if row[field].strip() == key]
        if len(matches) != 1:
            raise ValueError(f"{kind.capitalize()} not found or ambiguous: {key}")
        fields = _preserved_fields(
            name, (*required, "id") if field == "id" else required
        )
        _write(name, fields, [row for row in rows if row is not matches[0]])
    return f"Deleted {kind}: {key}"
