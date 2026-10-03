"""Deletion and exact history selectors shared with the TUI."""

import argparse

from .. import storage
from . import Command


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("kind", choices=("book", "goal", "session", "habit", "log"))
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--key", help="Exact title/name, or session/log ID")
    selector.add_argument(
        "--list", dest="list_records", action="store_true", help="List deletion keys"
    )


def run(args: argparse.Namespace) -> int:
    kind = args.kind
    assert isinstance(kind, str)
    if not args.list_records:
        print(storage.delete_record(kind, args.key))
        return 0
    if kind == "session":
        for session in storage.load_sessions_csv():
            print(
                f"{session['id']}\t{session['start']}\t{session['title']}\t{session['duration']}s"
            )
    elif kind == "log":
        for log in storage.load_log_csv():
            print(f"{log['id']}\t{log['timestamp']}\t{log['message']}")
    elif kind == "book":
        for book in storage.load_read_csv():
            print(book["title"])
    elif kind == "goal":
        for goal in storage.load_goals_csv():
            print(goal["title"])
    else:
        for habit in storage.load_habits_csv():
            print(habit["name"])
    return 0


def get_command() -> Command:
    return Command(
        "delete",
        "Delete a book, goal, session, habit, or log",
        configure_parser,
        run,
        mutates=lambda args: not args.list_records,
    )
