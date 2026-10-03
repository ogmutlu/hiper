import argparse
import datetime as dt

from .. import storage
from ..timeutil import local_datetime
from . import Command


def log_configure_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument("message", nargs="?", help="Message to append to log.csv")
    p.add_argument(
        "--last", "-l", help="Show logs from the last duration (e.g., 5m, 1h)"
    )
    p.add_argument(
        "--since", help="Show logs since this date/time (ISO datetime or YYYY-MM-DD)"
    )
    p.add_argument(
        "--until", help="Show logs until this date/time (ISO datetime or YYYY-MM-DD)"
    )
    p.add_argument(
        "--all", action="store_true", help="Show all logs (no date filtering)"
    )
    p.add_argument(
        "--at",
        help="Specify date/time for the log entry (ISO datetime, YYYY-MM-DD, YYYY-MM-DD HH:MM, or 'yesterday')",
    )


def _format_timestamp(ts: dt.datetime) -> str:
    """Format timestamp as 'YYYY-MM-DD, HH:MM'."""
    return ts.strftime("%Y-%m-%d, %H:%M")


def _parse_datetime(date_str: str, is_until: bool = False) -> dt.datetime:
    """Parse a date/datetime string.

    Tries ISO datetime format first, then YYYY-MM-DD date format.
    For dates, --since uses start of day, --until uses end of day.
    """
    date_str = date_str.strip()
    if len(date_str) == 10:
        date_obj = dt.date.fromisoformat(date_str)
        return dt.datetime.combine(date_obj, dt.time.max if is_until else dt.time.min)
    try:
        return local_datetime(date_str)
    except ValueError:
        pass
    try:
        date_obj = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
        if is_until:
            return dt.datetime.combine(date_obj, dt.time.max)
        else:
            return dt.datetime.combine(date_obj, dt.time.min)
    except ValueError:
        pass
    raise ValueError(
        f"Invalid date/time format '{date_str}'. Use ISO datetime (e.g., 2024-01-15T10:30:00) or date (YYYY-MM-DD)"
    )


def _parse_at_datetime(at_str: str) -> dt.datetime:
    """Parse the --at date/time string.

    Supports:
    - ISO datetime format (e.g., 2024-01-15T10:30:00)
    - Date format YYYY-MM-DD (uses current time)
    - Date and time format YYYY-MM-DD HH:MM
    - Special case: "yesterday" (same time as now, but yesterday)
    """
    at_str = at_str.strip().lower()
    if at_str == "yesterday":
        now = dt.datetime.now()
        return now - dt.timedelta(days=1)
    if len(at_str) == 10:
        return dt.datetime.combine(
            dt.date.fromisoformat(at_str), dt.datetime.now().time()
        )
    try:
        return local_datetime(at_str)
    except ValueError:
        pass
    try:
        return dt.datetime.strptime(at_str, "%Y-%m-%d %H:%M")
    except ValueError:
        pass
    try:
        date_obj = dt.datetime.strptime(at_str, "%Y-%m-%d").date()
        now = dt.datetime.now()
        return dt.datetime.combine(date_obj, now.time())
    except ValueError:
        pass
    raise ValueError(
        f"Invalid --at date/time format '{at_str}'. Use ISO datetime (e.g., 2024-01-15T10:30:00), YYYY-MM-DD, YYYY-MM-DD HH:MM, or 'yesterday'"
    )


def _print_logs_today() -> int:
    """Print logs from today."""
    today = dt.date.today()
    logs = storage.load_log_csv()
    today_logs: list[tuple[dt.datetime, str]] = []
    for log in logs:
        ts = log.get("timestamp")
        if isinstance(ts, dt.datetime):
            if ts.date() == today:
                msg_obj = log.get("message", "")
                msg = str(msg_obj)
                today_logs.append((ts, msg))
    if not today_logs:
        print("No logs found for today")
        return 0
    today_logs.sort(key=lambda row: row[0])
    print("--------------------------------")
    for ts, msg in today_logs:
        ts_str = _format_timestamp(ts)
        print(f"{ts_str} - {msg}")
    return 0


def _print_logs_since(duration: str) -> int:
    """Print logs within the provided duration string (e.g., 5m, 1h)."""
    try:
        seconds = storage.parse_duration(duration)
    except ValueError as e:
        print(f"Error: invalid --last duration '{duration}': {e}")
        return 1
    cutoff = dt.datetime.now() - dt.timedelta(seconds=seconds)
    logs = storage.load_log_csv()
    recent: list[tuple[dt.datetime, str]] = []
    for log in logs:
        ts = log.get("timestamp")
        if isinstance(ts, dt.datetime) and ts >= cutoff:
            msg_obj = log.get("message", "")
            msg = str(msg_obj)
            recent.append((ts, msg))
    if not recent:
        print(f"No logs found in the last {duration}")
        return 0
    recent.sort(key=lambda row: row[0])
    for ts, msg in recent:
        ts_str = _format_timestamp(ts)
        print(f"{ts_str} - {msg}")
    return 0


def _print_logs_range(since: dt.datetime | None, until: dt.datetime | None) -> int:
    """Print logs between since and until dates (inclusive)."""
    logs = storage.load_log_csv()
    filtered: list[tuple[dt.datetime, str]] = []
    for log in logs:
        ts = log.get("timestamp")
        if not isinstance(ts, dt.datetime):
            continue
        if since is not None and ts < since:
            continue
        if until is not None and ts > until:
            continue
        msg_obj = log.get("message", "")
        msg = str(msg_obj)
        filtered.append((ts, msg))
    if not filtered:
        since_str = since.strftime("%Y-%m-%d %H:%M") if since else "forever"
        until_str = until.strftime("%Y-%m-%d %H:%M") if until else "now"
        print(f"No logs found between {since_str} and {until_str}")
        return 0
    filtered.sort(key=lambda row: row[0])
    for ts, msg in filtered:
        ts_str = _format_timestamp(ts)
        print(f"{ts_str} - {msg}")
    return 0


def log_run(args: argparse.Namespace) -> int:
    filtering = bool(args.all or args.last or args.since or args.until)
    if args.message and filtering:
        raise ValueError("a log message cannot be combined with display filters")
    if args.at and (not args.message or filtering):
        raise ValueError("--at requires a log message")
    if sum((bool(args.all), bool(args.last), bool(args.since or args.until))) > 1:
        raise ValueError("use --all, --last, or --since/--until")
    if args.all:
        return _print_logs_range(None, None)
    if args.since or args.until:
        since: dt.datetime | None = None
        until: dt.datetime | None = None
        if args.since:
            try:
                since = _parse_datetime(args.since, is_until=False)
            except ValueError as e:
                print(f"Error: {e}")
                return 1
        if args.until:
            try:
                until = _parse_datetime(args.until, is_until=True)
            except ValueError as e:
                print(f"Error: {e}")
                return 1
        if since and until is None:
            until = dt.datetime.now()
        if since and until and (since > until):
            raise ValueError("since must be on or before until")
        return _print_logs_range(since, until)
    if args.last:
        return _print_logs_since(args.last)
    message = str(args.message or "").strip()
    if not message:
        return _print_logs_today()
    if args.at:
        try:
            timestamp = _parse_at_datetime(args.at)
        except ValueError as e:
            print(f"Error: {e}")
            return 1
    else:
        timestamp = dt.datetime.now()
    storage.append_log_csv(message, timestamp)
    return _print_logs_today()


def get_command() -> Command:
    return Command(
        name="log",
        help="Append a message or view recent logs.",
        description="Append a message with the current timestamp to log.csv, or list log entries. Use --at to specify a date/time for the entry. Use --all to show all logs, --last for recent duration (e.g. 5m, 1h), or --since/--until to filter by date range (ISO datetime or YYYY-MM-DD).",
        configure_parser=log_configure_parser,
        run=log_run,
        mutates=lambda args: (
            bool(args.message)
            and not (args.all or args.last or args.since or args.until)
        ),
    )
