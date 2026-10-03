import argparse
import datetime as dt

from .. import config, storage
from ..defaults import DEFAULT_WORK_PER_DAY
from ..models import Goal, GoalSummary
from ..planning import calculate_start_by
from . import Command


def _get_seconds_per_work_day() -> int:
    """Read configured work-per-day duration (defaults to 8h)."""
    work_per_day = config.get_config("work_per_day", DEFAULT_WORK_PER_DAY)
    return storage.parse_duration(work_per_day)


def _calculate_start_by(
    estimate_seconds: int, deadline: dt.date, time_worked_seconds: int
) -> dt.date:
    """Calculate the latest start date considering estimate, deadline, and time already worked.

    Deadline day is not workable. We can work 8 hours per day.
    """
    return calculate_start_by(
        estimate_seconds, deadline, time_worked_seconds, _get_seconds_per_work_day()
    )


def _update_time_worked(goals: list[Goal]) -> list[Goal]:
    """Update time_worked_seconds for all goals based on current sessions.csv."""
    for goal in goals:
        title_obj = goal.get("title")
        goal["time_worked_seconds"] = storage.get_time_worked_for_title(
            title_obj, after_timestamp=goal["estimate_timestamp"]
        )
        goal["time_worked_formatted"] = storage.format_hms(goal["time_worked_seconds"])
        estimate_obj = goal.get("estimate_seconds")
        deadline_obj = goal.get("deadline")
        time_worked_obj = goal.get("time_worked_seconds", 0)
        goal["start_by"] = (
            _calculate_start_by(estimate_obj, deadline_obj, time_worked_obj)
            if estimate_obj > 0 and deadline_obj is not None
            else None
        )
    return goals


def build_goal_summary(goal: Goal) -> GoalSummary | None:
    """Return a normalized goal summary for listing."""
    title_obj = goal.get("title")
    if not title_obj:
        return None
    estimate_seconds_obj = goal.get("estimate_seconds", 0)
    estimate_seconds = estimate_seconds_obj
    estimate_timestamp = goal.get("estimate_timestamp")
    if isinstance(estimate_timestamp, dt.datetime):
        time_worked_seconds = storage.get_time_worked_for_title(
            title_obj, after_timestamp=estimate_timestamp
        )
    else:
        time_worked_seconds = storage.get_time_worked_for_title(title_obj)
    deadline_obj = goal.get("deadline")
    start_by_obj = goal.get("start_by")
    if isinstance(deadline_obj, dt.date) and estimate_seconds > 0:
        start_by_obj = _calculate_start_by(
            estimate_seconds, deadline_obj, time_worked_seconds
        )
    else:
        start_by_obj = start_by_obj if isinstance(start_by_obj, dt.date) else None
    return {
        "title": title_obj,
        "estimate_seconds": estimate_seconds,
        "estimate": storage.format_hms(estimate_seconds)
        if estimate_seconds > 0
        else "",
        "time_worked_seconds": time_worked_seconds,
        "time_worked": storage.format_hms(time_worked_seconds),
        "remaining": storage.format_hms(max(0, estimate_seconds - time_worked_seconds))
        if estimate_seconds > 0
        else "",
        "deadline": deadline_obj if isinstance(deadline_obj, dt.date) else None,
        "start_by": start_by_obj if isinstance(start_by_obj, dt.date) else None,
    }


def _list_goals(goals: list[Goal], show_all: bool) -> int:
    summaries: list[tuple[GoalSummary, Goal]] = []
    for goal in goals:
        built = build_goal_summary(goal)
        if not built:
            continue
        if not show_all and built["estimate_seconds"] <= 0:
            continue
        summaries.append((built, goal))
    if not summaries:
        print(
            "No goals found with current estimates."
            if not show_all
            else "No goals found in goals.csv."
        )
        return 0
    summaries = sorted(
        summaries,
        key=lambda pair: (
            pair[0]["start_by"] if pair[0].get("start_by") else dt.date.max,
            pair[0]["deadline"] if pair[0].get("deadline") else dt.date.max,
            pair[0]["title"],
        ),
    )
    header = "All goals:" if show_all else "Goals with current estimates:"
    print(header)
    if show_all:
        for summary, _goal in summaries:
            parts = [
                f"{summary['title']}",
                f"estimate {summary['estimate']}"
                if summary.get("estimate")
                else "estimate (not set)",
                f"worked {summary['time_worked']}",
                f"remaining {summary['remaining']}"
                if summary.get("remaining")
                else "remaining (n/a)",
            ]
            deadline_obj = summary.get("deadline")
            if isinstance(deadline_obj, dt.date):
                parts.append(f"deadline {deadline_obj.strftime('%Y-%m-%d')}")
            start_by_obj = summary.get("start_by")
            if isinstance(start_by_obj, dt.date):
                parts.append(f"start by {start_by_obj.strftime('%Y-%m-%d')}")
            print("  - " + ", ".join(parts))
    else:
        for idx, (summary, goal) in enumerate(summaries):
            title = summary["title"]
            _print_goal_details(title, goal)
            if idx < len(summaries) - 1:
                print()
    return 0


def _print_goal_details(title: str, goal: Goal) -> None:
    summary = build_goal_summary(goal)
    total_time_worked_seconds = storage.get_time_worked_for_title(title)
    total_time_worked = storage.format_hms(total_time_worked_seconds)
    estimate_timestamp = goal.get("estimate_timestamp")
    if isinstance(estimate_timestamp, dt.datetime):
        time_worked_seconds = storage.get_time_worked_for_title(
            title, after_timestamp=estimate_timestamp
        )
    else:
        time_worked_seconds_obj = summary.get("time_worked_seconds") if summary else 0
        time_worked_seconds = time_worked_seconds_obj
    time_worked = storage.format_hms(time_worked_seconds)
    print(f"Goal: {title}")
    print(f"  Total time worked: {total_time_worked}")
    if isinstance(estimate_timestamp, dt.datetime):
        print(f"  Time worked (after estimate): {time_worked}")
    else:
        print(f"  Time worked: {time_worked}")
    if not summary:
        print("  Estimate: (not set)")
        print("  Deadline: (not set)")
        print("  Start by: (not set)")
        return
    estimate_obj = summary.get("estimate_seconds", 0)
    deadline_obj = summary.get("deadline")
    start_by_obj = summary.get("start_by")
    if estimate_obj <= 0:
        print("  Estimate: (not set)")
        print("  Deadline: (not set)")
        print("  Start by: (not set)")
        return
    estimate = storage.format_hms(estimate_obj)
    remaining_seconds = max(0, int(estimate_obj) - int(time_worked_seconds))
    remaining = storage.format_hms(remaining_seconds)
    print(f"  Estimate: {estimate}")
    if remaining_seconds > 0:
        print(f"  Remaining: {remaining}")
    else:
        print("  Remaining: 0 (completed!)")
    if isinstance(deadline_obj, dt.date):
        print(f"  Deadline: {deadline_obj.strftime('%Y-%m-%d')}")
        if isinstance(start_by_obj, dt.date):
            start_by_str = start_by_obj.strftime("%Y-%m-%d")
            print(f"  Start by: {start_by_str} morning")
        else:
            print("  Start by: (not calculated)")
    else:
        print("  Deadline: (not set)")
        print("  Start by: (not set - deadline required)")


def prefokus_configure_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument("--title", "-t", required=False, help="Goal title")
    p.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="List all goals even without an estimate",
    )
    p.add_argument(
        "--estimate",
        "-e",
        help="Estimated time needed (e.g., 20h, 1h30m). Required for new goals.",
    )
    p.add_argument(
        "--deadline",
        "-d",
        help="Deadline date (YYYY-MM-DD). Optional. Deadline day is not workable.",
    )


def prefokus_run(args: argparse.Namespace) -> int:
    title = (args.title or "").strip()
    if not title:
        if args.estimate or args.deadline:
            print("Error: --title is required when setting an estimate or deadline")
            return 1
        goals = _update_time_worked(storage.load_goals_csv())
        return _list_goals(goals, show_all=args.all)
    goals = storage.load_goals_csv()
    goal: Goal | None = None
    for g in goals:
        if g["title"] == title:
            goal = g
            break
    if goal is not None and (not args.estimate) and (not args.deadline):
        _print_goal_details(title, goal)
        return 0
    if goal is None:
        if not args.estimate:
            print("Error: --estimate is required for new goals")
            return 1
        try:
            estimate_seconds = storage.parse_duration(args.estimate)
            if estimate_seconds <= 0:
                raise ValueError("estimate must be greater than zero")
        except ValueError as e:
            print(f"Error: invalid estimate '{args.estimate}': {e}")
            return 1
        deadline: dt.date | None = None
        if args.deadline:
            try:
                deadline = dt.datetime.strptime(args.deadline, "%Y-%m-%d").date()
            except ValueError:
                print(
                    f"Error: invalid deadline format '{args.deadline}'. Use YYYY-MM-DD"
                )
                return 1
        estimate_timestamp = dt.datetime.now()
        time_worked_seconds = storage.get_time_worked_for_title(
            title, after_timestamp=estimate_timestamp
        )
        start_by: dt.date | None = None
        if deadline:
            start_by = _calculate_start_by(
                estimate_seconds, deadline, time_worked_seconds
            )
        goal = {
            "title": title,
            "estimate_seconds": estimate_seconds,
            "estimate_formatted": storage.format_hms(estimate_seconds),
            "estimate_timestamp": estimate_timestamp,
            "deadline": deadline,
            "time_worked_seconds": time_worked_seconds,
            "time_worked_formatted": storage.format_hms(time_worked_seconds),
            "start_by": start_by,
        }
        goals.append(goal)
    else:
        if args.estimate:
            try:
                goal["estimate_seconds"] = storage.parse_duration(args.estimate)
                if goal["estimate_seconds"] <= 0:
                    raise ValueError("estimate must be greater than zero")
                goal["estimate_formatted"] = storage.format_hms(
                    goal["estimate_seconds"]
                )
                goal["estimate_timestamp"] = dt.datetime.now()
            except ValueError as e:
                print(f"Error: invalid estimate '{args.estimate}': {e}")
                return 1
        if args.deadline:
            try:
                goal["deadline"] = dt.datetime.strptime(
                    args.deadline, "%Y-%m-%d"
                ).date()
            except ValueError:
                print(
                    f"Error: invalid deadline format '{args.deadline}'. Use YYYY-MM-DD"
                )
                return 1
        estimate_timestamp = goal.get("estimate_timestamp")
        if isinstance(estimate_timestamp, dt.datetime):
            goal["time_worked_seconds"] = storage.get_time_worked_for_title(
                title, after_timestamp=estimate_timestamp
            )
        else:
            goal["time_worked_seconds"] = storage.get_time_worked_for_title(title)
        goal["time_worked_formatted"] = storage.format_hms(goal["time_worked_seconds"])
        estimate_obj = goal.get("estimate_seconds")
        deadline_obj = goal.get("deadline")
        time_worked_obj = goal.get("time_worked_seconds", 0)
        goal["start_by"] = (
            _calculate_start_by(estimate_obj, deadline_obj, time_worked_obj)
            if estimate_obj > 0 and deadline_obj is not None
            else None
        )
    goals = _update_time_worked(goals)
    storage.save_goals_csv(goals)
    _print_goal_details(title, goal)
    return 0


def get_command() -> Command:
    return Command(
        name="prefokus",
        help="Plan focus goals with estimates and optional deadlines",
        description="Create or update goals with time estimates and optional deadlines. If a deadline is provided, calculates when you should start working to meet it (assuming 8 hours of work per day).",
        configure_parser=prefokus_configure_parser,
        run=prefokus_run,
        mutates=lambda args: bool(args.estimate or args.deadline),
    )
