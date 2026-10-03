import argparse
import datetime as dt

from .. import messages as msgs
from .. import storage
from ..models import Session
from ..timeutil import local_datetime
from . import Command


def _parse_duration(s: str) -> int:
    return storage.parse_duration(s)


def _get_duration(row: Session) -> int:
    return row["duration"]


def _get_start(row: Session) -> dt.datetime | None:
    return row["start"]


def _parse_start(s: str | None, duration_s: int) -> dt.datetime:
    if not s:
        end = dt.datetime.now()
        return end - dt.timedelta(seconds=duration_s)
    s = s.strip()
    try:
        return local_datetime(s)
    except ValueError:
        pass
    try:
        hh, mm = s.split(":")
        now = dt.datetime.now()
        return now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except ValueError:
        pass
    raise ValueError("start must be ISO datetime or HH:MM")


def postfokus_configure_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--duration", "-d", help="Duration (e.g., 25m, 1h30m, 1h30s, 1500s)."
    )
    p.add_argument(
        "--start",
        "-s",
        help="Start time (ISO or HH:MM). If omitted, inferred from now - duration",
    )
    p.add_argument(
        "--end",
        "-e",
        help="End time (ISO or HH:MM). If omitted, inferred from start + duration",
    )
    p.add_argument(
        "--title",
        "-t",
        help="Session title. With no --duration, filters statistics to this title.",
        default=None,
    )
    p.add_argument("--titles", action="store_true", help="Show per-title breakdown")
    p.add_argument(
        "--since",
        help="Only include sessions starting on/after this date (YYYY-MM-DD).",
    )
    p.add_argument(
        "--until",
        help="Only include sessions starting on/before this date (YYYY-MM-DD).",
    )
    p.add_argument(
        "--table",
        action="store_true",
        help="Show daily statistics in table format (last 10 days, or adjusted by --since/--until)",
    )


def _filter_rows_range(
    rows: list[Session], since: dt.date | None, until: dt.date | None
) -> list[Session]:
    filtered: list[Session] = []
    for r in rows:
        start = _get_start(r)
        if start is None:
            continue
        start_date = start.date()
        if since is not None and start_date < since:
            continue
        if until is not None and start_date > until:
            continue
        filtered.append(r)
    return filtered


def _parse_since(since_str: str | None) -> dt.date | None:
    if not since_str:
        return None
    try:
        return dt.datetime.strptime(since_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("since must be YYYY-MM-DD") from None


def _parse_until(until_str: str | None) -> dt.date | None:
    if not until_str:
        return None
    try:
        return dt.datetime.strptime(until_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("until must be YYYY-MM-DD") from None


def _print_statistics(
    title_filter: str | None = None,
    since: dt.date | None = None,
    until: dt.date | None = None,
) -> int:
    rows = storage.load_sessions_csv()
    if title_filter:
        rows = [r for r in rows if (r.get("title") or "") == title_filter]
    rows = _filter_rows_range(rows, since, until)
    print(msgs.stats_header(title_filter))
    if not rows:
        print(msgs.stats_line("sessions", "0"))
        return 0
    total_sessions = len(rows)
    total_seconds = sum(_get_duration(r) for r in rows)
    now = dt.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    last7_start = today_start - dt.timedelta(days=6)
    last30_start = today_start - dt.timedelta(days=29)
    today_seconds = sum(
        _get_duration(r)
        for r in rows
        if (start := _get_start(r)) is not None
        and today_start.date() <= start.date() <= now.date()
    )
    week_seconds = sum(
        _get_duration(r)
        for r in rows
        if (start := _get_start(r)) is not None
        and last7_start.date() <= start.date() <= now.date()
    )
    month_seconds = sum(
        _get_duration(r)
        for r in rows
        if (start := _get_start(r)) is not None
        and last30_start.date() <= start.date() <= now.date()
    )
    avg_seconds = total_seconds // total_sessions if total_sessions else 0
    print("--------------------------------")
    print(msgs.stats_line("sessions", str(total_sessions)))
    print(msgs.stats_line("total", storage.format_hms(total_seconds)))
    print(msgs.stats_line("today", storage.format_hms(today_seconds)))
    print(msgs.stats_line("last 7 days", storage.format_hms(week_seconds)))
    print(msgs.stats_line("last 30 days", storage.format_hms(month_seconds)))
    min_date = None
    for r in rows:
        start = _get_start(r)
        if start is None:
            continue
        start_date = start.date()
        if min_date is None or start_date < min_date:
            min_date = start_date
    days_total = (today_start.date() - min_date).days + 1 if min_date else 0
    avg_per_day_all = total_seconds // days_total if days_total > 0 else 0

    def _avg_window(
        start_date: dt.date, end_date: dt.date, rows_subset: list[Session]
    ) -> int:
        span_days = (end_date - start_date).days + 1
        if span_days <= 0:
            return 0
        window_total = sum(_get_duration(r) for r in rows_subset)
        return window_total // span_days

    window_start_7 = last7_start.date()
    window_rows_7 = [
        r
        for r in rows
        if (start := _get_start(r)) is not None
        and start.date() >= window_start_7
        and (start.date() <= today_start.date())
    ]
    avg_per_day_last7 = _avg_window(window_start_7, today_start.date(), window_rows_7)
    window_start_30 = last30_start.date()
    window_rows_30 = [
        r
        for r in rows
        if (start := _get_start(r)) is not None
        and start.date() >= window_start_30
        and (start.date() <= today_start.date())
    ]
    avg_per_day_last30 = _avg_window(
        window_start_30, today_start.date(), window_rows_30
    )
    print(msgs.stats_line("average per day", storage.format_hms(avg_per_day_all)))
    print(
        msgs.stats_line(
            "average per day last 7 days", storage.format_hms(avg_per_day_last7)
        )
    )
    print(
        msgs.stats_line(
            "average per day last 30 days", storage.format_hms(avg_per_day_last30)
        )
    )
    print(msgs.stats_line("average session length", storage.format_hms(avg_seconds)))
    return 0


def _print_table(
    title_filter: str | None = None,
    since: dt.date | None = None,
    until: dt.date | None = None,
    by_title: bool = False,
) -> int:
    """Print daily statistics in table format."""
    rows = storage.load_sessions_csv()
    if title_filter:
        rows = [r for r in rows if (r.get("title") or "") == title_filter]
    rows = _filter_rows_range(rows, since, until)
    today = dt.date.today()
    if since and until:
        start_date = since
        end_date = until
    elif since:
        start_date = since
        end_date = min(today, since + dt.timedelta(days=9))
    elif until:
        end_date = until
        start_date = end_date - dt.timedelta(days=9)
    else:
        end_date = today
        start_date = today - dt.timedelta(days=9)
    daily_totals: dict[dt.date, int] = {}
    daily_by_title: dict[str, dict[dt.date, int]] = {}
    for r in rows:
        start = _get_start(r)
        if start is None:
            continue
        session_date = start.date()
        if session_date < start_date or session_date > end_date:
            continue
        duration = _get_duration(r)
        if session_date not in daily_totals:
            daily_totals[session_date] = 0
        daily_totals[session_date] += duration
        if by_title:
            title_str = r.get("title")
            title = str(title_str).strip() if title_str else "(unnamed)"
            if title not in daily_by_title:
                daily_by_title[title] = {}
            if session_date not in daily_by_title[title]:
                daily_by_title[title][session_date] = 0
            daily_by_title[title][session_date] += duration
    if by_title:
        print(msgs.stats_header("by title (daily table)"))
        titles = sorted(daily_by_title.keys())
        for title in titles:
            label = title if title else "(unnamed)"
            print(f"\n{label}:")
            title_table_parts: list[str] = []
            current_date = start_date
            while current_date <= end_date:
                day_name = current_date.strftime("%a")
                day_num = str(current_date.day)
                month_name = current_date.strftime("%b")
                date_str = f"{day_name} {day_num} {month_name}"
                date_str_padded = f"{date_str:12}"
                duration_seconds = daily_by_title[title].get(current_date, 0)
                if duration_seconds > 0:
                    title_table_parts.append(
                        f"{date_str_padded}:   [{storage.format_hms(duration_seconds)}]"
                    )
                else:
                    title_table_parts.append(f"{date_str_padded}:   []")
                current_date += dt.timedelta(days=1)
            print("\n".join(title_table_parts))
        print("--------------------------------")
        return 0
    else:
        if title_filter:
            print(msgs.stats_header(title_filter))
        else:
            print(msgs.stats_header(None))
        print("Daily table:")
        main_table_parts: list[str] = []
        current_date = start_date
        while current_date <= end_date:
            day_name = current_date.strftime("%a")
            day_num = str(current_date.day)
            month_name = current_date.strftime("%b")
            date_str = f"{day_name} {day_num} {month_name}"
            date_str_padded = f"{date_str:12}"
            duration_seconds = daily_totals.get(current_date, 0)
            if duration_seconds > 0:
                main_table_parts.append(
                    f"{date_str_padded}: [{storage.format_hms(duration_seconds)}]"
                )
            else:
                main_table_parts.append(f"{date_str_padded}: []")
            current_date += dt.timedelta(days=1)
        print("\n".join(main_table_parts))
        print("--------------------------------")
        return 0


def _print_statistics_by_title(
    since: dt.date | None = None, until: dt.date | None = None
) -> int:
    rows = storage.load_sessions_csv()
    rows = _filter_rows_range(rows, since, until)
    print(msgs.stats_header("by title"))
    if not rows:
        print(msgs.stats_line("sessions", "0"))
        return 0
    agg: dict[str, dict[str, int]] = {}
    for r in rows:
        title_str = r.get("title")
        title = str(title_str).strip() if title_str else ""
        entry = agg.setdefault(title, {"sessions": 0, "total": 0})
        entry["sessions"] += 1
        entry["total"] += _get_duration(r)
    items = sorted(agg.items(), key=lambda kv: kv[1]["total"], reverse=True)
    for title, data in items:
        label = title if title else "(unnamed)"
        print("--------------------------------")
        print(msgs.stats_line(f"{label} sessions", str(data["sessions"])))
        print(msgs.stats_line(f"{label} total", storage.format_hms(data["total"])))
    print("--------------------------------")
    return 0


def postfokus_run(args: argparse.Namespace) -> int:
    try:
        since_date = _parse_since(args.since)
        until_date = _parse_until(args.until)
    except ValueError as e:
        print(msgs.invalid_X(str(e), "since"))
        return 2
    if since_date and until_date and (since_date > until_date):
        raise ValueError("since must be on or before until")
    if not args.duration:
        if args.table:
            if args.titles and (not args.title):
                return _print_table(None, since_date, until_date, by_title=True)
            return _print_table(
                args.title or None, since_date, until_date, by_title=False
            )
        if args.titles and (not args.title):
            return _print_statistics_by_title(since_date, until_date)
        return _print_statistics(args.title or None, since_date, until_date)
    try:
        duration_s = _parse_duration(args.duration)
    except ValueError as e:
        print(msgs.invalid_X(str(e), "duration"))
        return 2
    end: dt.datetime | None = None
    if args.end:
        try:
            end = _parse_start(args.end, duration_s)
        except ValueError as e:
            print(msgs.invalid_X(str(e), "end"))
            return 2
    try:
        if args.start:
            start = _parse_start(args.start, duration_s)
        elif end is not None:
            start = end - dt.timedelta(seconds=duration_s)
        else:
            start = _parse_start(None, duration_s)
    except ValueError as e:
        print(msgs.invalid_X(str(e), "start"))
        return 2
    if end is None:
        end = start + dt.timedelta(seconds=duration_s)
    if end < start:
        raise ValueError("session end must be on or after start")
    path = storage.save_session_csv(args.title or "", start, end, duration_s)
    print(msgs.saved_session_line(storage.format_hms(duration_s)))
    print(msgs.saved_path_line(path))
    return 0


def get_command() -> Command:
    return Command(
        name="postfokus",
        help="Show statistics or add a past focus session.",
        description="Record a past focus session by providing duration and optional start time and title.",
        configure_parser=postfokus_configure_parser,
        run=postfokus_run,
        mutates=lambda args: bool(args.duration),
    )
