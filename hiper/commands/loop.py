import argparse
import datetime as dt

from .. import storage
from ..habits import day_abbr as _get_day_abbr_for_date
from ..habits import is_scheduled_today as _is_habit_scheduled_today
from ..habits import match_habit as _check_habit_match
from ..habits import parse_frequency as _parse_frequency
from ..habits import today_day_abbr as _get_today_day_abbr
from ..models import Habit
from . import Command


def loop_configure_parser(p: argparse.ArgumentParser) -> None:
    subparsers = p.add_subparsers(dest="loop_subcommand", help="loop subcommands")
    add_parser = subparsers.add_parser("add", help="Add a new habit")
    add_parser.add_argument("--title", "-t", required=True, help="Habit name")
    add_parser.add_argument(
        "--freq",
        "-f",
        required=True,
        help="Frequency: 'daily' for every day, or comma-separated days like 'mon,tue,sat'",
    )
    subparsers.add_parser("today", help="Show today's habit status")
    stats_parser = subparsers.add_parser(
        "statistics", help="Show completion statistics"
    )
    stats_parser.add_argument(
        "--since", help="Only include logs starting on/after this date (YYYY-MM-DD)"
    )
    stats_parser.add_argument(
        "--until", help="Only include logs up to/on this date (YYYY-MM-DD)"
    )


def _print_today(habits: list[Habit]) -> None:
    today = dt.date.today()
    scheduled = [
        habit for habit in habits if _is_habit_scheduled_today(habit["frequency"])
    ]
    if not scheduled:
        print(f"No habits scheduled for today ({today.isoformat()})")
        return
    messages = [
        log["message"].strip()
        for log in storage.load_log_csv()
        if log["timestamp"] is not None and log["timestamp"].date() == today
    ]
    done: list[Habit] = []
    pending: list[Habit] = []
    for habit in scheduled:
        target = (
            done
            if any(
                _check_habit_match(message, habit["name"]) is not None
                for message in messages
            )
            else pending
        )
        target.append(habit)
    print("=" * 50)
    print(f"Habits for {today.isoformat()} ({_get_today_day_abbr()})")
    print("=" * 50)
    for label, group in (("✓ Done:", done), ("✗ Not done:", pending)):
        if group:
            print(f"\n{label}")
            for habit in group:
                print(f"  {habit['name']} ({habit['frequency']})")


def _print_statistics(
    habits: list[Habit], since: dt.date | None, until: dt.date | None
) -> None:
    if since and until and since > until:
        raise ValueError("since must be on or before until")
    logs = storage.load_log_csv()
    today = dt.date.today()
    print("=" * 50)
    print("Habit Completion Statistics")
    print(f"From: {since or 'creation'} to {until or today}")
    print("=" * 50)
    rates: list[str] = []
    for habit in habits:
        scheduled = _parse_frequency(habit["frequency"])
        start = max(since or habit["created_at"].date(), habit["created_at"].date())
        end = min(until or today, today)
        completed: dict[dt.date, str] = {}
        for log in logs:
            timestamp = log["timestamp"]
            if timestamp is None:
                continue
            day = timestamp.date()
            if (
                not (start <= day <= end)
                or _get_day_abbr_for_date(day) not in scheduled
            ):
                continue
            match = _check_habit_match(log["message"], habit["name"])
            if match is not None:
                completed[day] = match
        cells: list[str] = []
        expected = 0
        day = start
        while day <= end:
            if _get_day_abbr_for_date(day) in scheduled:
                expected += 1
                cells.append(
                    f"[{completed[day] or '█'}]" if day in completed else "[ ]"
                )
            else:
                cells.append(".")
            day += dt.timedelta(days=1)
        if cells:
            print(f"{habit['name']}: {''.join(cells)}")
        count = len(completed)
        rate = f"{count / expected * 100:.1f}%" if expected else "N/A"
        rates.append(f"{habit['name']}: {count}/{expected} ({rate})")
    print("=" * 50)
    for line in rates:
        print(line)


def loop_run(args: argparse.Namespace) -> int:
    subcommand = getattr(args, "loop_subcommand", None)
    habits = storage.load_habits_csv()
    if subcommand == "add":
        name = args.title.strip()
        frequency = args.freq.strip().lower()
        if not name:
            raise ValueError("habit name cannot be empty")
        _parse_frequency(frequency)
        if any(habit["name"] == name for habit in habits):
            raise ValueError(f"Habit {name!r} already exists")
        habits.append(
            Habit(name=name, frequency=frequency, created_at=dt.datetime.now())
        )
        storage.save_habits_csv(habits)
        print(f"Added habit '{name}' with frequency '{frequency}'")
        return 0
    if not habits:
        print("No habits defined. Use 'hiper loop add --title NAME --freq FREQUENCY'.")
        return 0
    if subcommand == "statistics":
        since = dt.date.fromisoformat(args.since) if args.since else None
        until = dt.date.fromisoformat(args.until) if args.until else None
        _print_statistics(habits, since, until)
        return 0
    _print_today(habits)
    if subcommand != "today":
        print("\n" + "=" * 50)
        print("All Habits")
        print("=" * 50)
        for habit in habits:
            print(f"  {habit['name']}: {habit['frequency']}")
    return 0


def get_command() -> Command:
    return Command(
        name="loop",
        help="Manage habits and track daily completion.",
        description="Add habits and check today's completion status.",
        configure_parser=loop_configure_parser,
        run=loop_run,
        mutates=lambda args: args.loop_subcommand == "add",
    )
