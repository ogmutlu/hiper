import argparse
import datetime as dt
import shlex
import subprocess
import sys

from .. import config, storage
from .. import messages as msgs
from ..defaults import DEFAULT_ESTIMATE_BAR, DEFAULT_TODAY_TIME
from ..rendering import _finalize_render, _format_duration, _tick_render
from ..session import SessionClock
from ..terminal import (
    TerminalSettings,
    _read_key_nonblocking,
    _restore_mode,
    _set_raw_mode,
)
from . import Command


def _save_session_csv(
    title: str | None,
    start: dt.datetime,
    end: dt.datetime,
    duration_s: int,
    comment: str | None = None,
) -> str:
    return storage.save_session_csv(
        title or "", start, end, duration_s, comment=comment or ""
    )


def _handle_save(
    title: str | None,
    start: dt.datetime,
    end: dt.datetime,
    elapsed_s: int,
    comment: str | None = None,
) -> None:
    """Save the session and print confirmation messages."""
    _finalize_render()
    path = _save_session_csv(title, start, end, elapsed_s, comment)
    print(msgs.saved_session_line(_format_duration(elapsed_s)))
    print(msgs.saved_path_line(path))


def _print_header(start_time: dt.datetime) -> None:
    print(msgs.started_at_line(start_time))


def _online_fokus_line(title: str | None, comment: str | None) -> str:
    status = title or ""
    if comment:
        status = f"{status} :: {comment}" if status else f":: {comment}"
    return f"fokus: {status}".rstrip()


def _format_online_status_line(nick: str, status: str, is_active: bool) -> str:
    title, separator, comment = status.partition(" :: ")
    if status.startswith(":: "):
        title, separator, comment = "", "::", status[3:]
    title = title.strip()
    comment = comment.strip() if separator else ""
    if is_active:
        if title and comment:
            return f":>{nick} is fokusing on {title} with comment {comment} right now"
        if title:
            return f":>{nick} is fokusing on {title} right now"
        if comment:
            return f":>{nick} is fokusing with comment {comment} right now"
        return f":>{nick} is fokusing right now"
    if title and comment:
        return f":>{nick} has fokused on {title} with comment {comment} last time"
    if title:
        return f":>{nick} has fokused on {title} last time"
    if comment:
        return f":>{nick} has fokused with comment {comment} last time"
    return f":>{nick} has fokused last time"


def _parse_save_command(cmd_line: str) -> tuple[bool, str | None]:
    try:
        parts = shlex.split(cmd_line)
    except ValueError:
        return False, None
    if not parts or parts[0].lower() != "save":
        return False, None
    if len(parts) == 1:
        return True, None
    if len(parts) == 3 and parts[1] == "--title" and parts[2].strip():
        return True, parts[2].strip()
    return False, None


def _parse_goal_command(cmd_line: str) -> tuple[bool, str | None, str | None]:
    """Parse a goal command like 'goal 5h' or 'goal 1h30m'.

    Returns:
        (is_goal_command, duration, error_message)
    """
    cmd_line = cmd_line.strip()
    if not cmd_line.split() or cmd_line.split()[0].lower() != "goal":
        return (False, None, None)
    try:
        parts = shlex.split(cmd_line)
    except ValueError:
        parts = cmd_line.split()
    if len(parts) == 1 and parts[0].lower() == "goal":
        return (True, None, "Usage: goal DURATION (e.g., goal 5h)")
    if len(parts) != 2:
        return (True, None, "Usage: goal DURATION (e.g., goal 5h)")
    duration = parts[1]
    try:
        if storage.parse_duration(duration) <= 0:
            raise ValueError("goal must be greater than zero")
    except ValueError as e:
        return (True, None, f"Invalid duration '{duration}': {e}")
    return (True, duration, None)


def fokus_configure_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument("--title", "-t", help="Optional title for the session", default=None)
    p.add_argument("--comment", help="Optional comment for the session", default=None)
    p.add_argument(
        "--goal",
        "-g",
        help="Target duration for this session (e.g., 60m, 1h30m). Overrides --clock config.",
        default=None,
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="In strict mode, pressing space asks for pause duration and runs 'hiper pause'",
    )
    p.add_argument(
        "--context",
        "-c",
        action="store_true",
        help="Show cumulative time focused on this title across all sessions (requires --title)",
    )
    p.add_argument(
        "--online",
        action="store_true",
        help="Write fokus status to data_dir/online/NICKNAME.txt and show other users' status below timers",
    )


def fokus_run(args: argparse.Namespace) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("fokus requires an interactive terminal")
    comment = getattr(args, "comment", None)
    goal_override: str | None = None
    goal_value: object = args.goal
    if goal_value is not None and not isinstance(goal_value, str):
        raise ValueError("goal must be a duration string")
    if goal_value:
        try:
            if storage.parse_duration(goal_value) <= 0:
                raise ValueError("goal must be greater than zero")
            goal_override = goal_value
        except ValueError as e:
            print(f"Error: invalid goal duration '{args.goal}': {e}")
            return 1
    start = dt.datetime.now()
    _print_header(start)
    estimate_seconds: int | None = None
    time_worked_before: int | None = None
    estimate_bar_enabled = (
        config.get_config("estimate_bar", DEFAULT_ESTIMATE_BAR).lower() == "true"
    )
    if estimate_bar_enabled and args.title:
        try:
            goals = storage.load_goals_csv()
            for goal in goals:
                if goal.get("title") == args.title:
                    est_sec = goal.get("estimate_seconds", 0)
                    estimate_seconds = est_sec
                    estimate_timestamp = goal.get("estimate_timestamp")
                    if isinstance(estimate_timestamp, dt.datetime):
                        time_worked_before = storage.get_time_worked_for_title(
                            args.title, after_timestamp=estimate_timestamp
                        )
                    else:
                        time_worked_obj = goal.get("time_worked_seconds", 0)
                        time_worked_before = time_worked_obj
                    break
        except (OSError, ValueError) as e:
            print(f"Error: failed to load goals: {e}")
    context_time_before: int | None = None
    if args.context:
        if not args.title:
            print("Error: --context requires --title")
            return 1
        context_time_before = storage.get_time_worked_for_title(args.title)
    today_time_before: int | None = None
    today_time_enabled = (
        config.get_config("today_time", DEFAULT_TODAY_TIME).lower() == "true"
    )
    if today_time_enabled:
        today_time_before = storage.get_time_worked_today()
    nick = (
        config.get_config("nick", "(not set)").strip()
        if getattr(args, "online", False)
        else ""
    )
    online_status_line: str | None = None
    wrote_online_fokus = False
    paused = False
    clock = SessionClock()
    pause_started: dt.datetime | None = None
    fd: int | None
    old: TerminalSettings | None
    fd, old = _set_raw_mode()
    is_first_render = True
    last_online_check_elapsed = -1
    try:
        if getattr(args, "online", False) and nick:
            other = storage.get_other_online_fokus_status(nick)
            if other:
                other_nick, other_title, is_active = other
                online_status_line = _format_online_status_line(
                    other_nick, other_title, is_active
                )
            storage.append_online_fokus_line(
                nick, _online_fokus_line(args.title, comment)
            )
            wrote_online_fokus = True
        _tick_render(
            0,
            goal_override,
            args.title,
            is_first_render,
            estimate_seconds,
            time_worked_before,
            context_time_before,
            today_time_before,
            online_status_line,
        )
        is_first_render = False
        last_whole = -1
        while True:
            now = dt.datetime.now()
            elapsed = clock.seconds
            if not paused:
                if elapsed != last_whole:
                    if (
                        getattr(args, "online", False)
                        and nick
                        and (elapsed >= last_online_check_elapsed + 10)
                    ):
                        last_online_check_elapsed = elapsed
                        other = storage.get_other_online_fokus_status(nick)
                        if other:
                            other_nick, other_title, is_active = other
                            online_status_line = _format_online_status_line(
                                other_nick, other_title, is_active
                            )
                        else:
                            online_status_line = None
                    _tick_render(
                        elapsed,
                        goal_override,
                        args.title,
                        is_first_render,
                        estimate_seconds,
                        time_worked_before,
                        context_time_before,
                        today_time_before,
                        online_status_line,
                    )
                    is_first_render = False
                    last_whole = elapsed
            else:
                last_whole = elapsed
            if not paused:
                key = _read_key_nonblocking(0.1)
                if key is None:
                    continue
                if key == " ":
                    clock.pause()
                    now = dt.datetime.now()
                    elapsed = clock.seconds
                    if args.strict:
                        _finalize_render()
                        _restore_mode(fd, old)
                        fd, old = (None, None)
                        print(
                            msgs.paused_line(current_time=now, elapsed_seconds=elapsed)
                        )
                        if getattr(args, "online", False) and nick:
                            storage.append_online_fokus_line(nick, "pause")
                        sys.stdout.write("Pause for: ")
                        sys.stdout.flush()
                        duration_input = sys.stdin.readline().strip()
                        if not duration_input:
                            print("\x1b[1A\x1b[K", end="", flush=True)
                            paused = True
                            pause_started = now
                            continue
                        try:
                            storage.parse_duration(duration_input)
                        except ValueError as e:
                            print(f"Error: invalid duration '{duration_input}': {e}")
                            resume_now = dt.datetime.now()
                            pause_dur_s = int((resume_now - now).total_seconds())
                            print(
                                msgs.resuming_line(
                                    _format_duration(pause_dur_s), resume_now
                                )
                            )
                            fd, old = _set_raw_mode()
                            paused = False
                            clock.resume()
                            if wrote_online_fokus:
                                storage.append_online_fokus_line(
                                    nick, _online_fokus_line(args.title, comment)
                                )
                            pause_started = None
                            last_whole = -1
                            is_first_render = True
                            _tick_render(
                                elapsed,
                                goal_override,
                                args.title,
                                is_first_render,
                                estimate_seconds,
                                time_worked_before,
                                context_time_before,
                                today_time_before,
                                online_status_line,
                            )
                            is_first_render = False
                            continue
                        pause_start_time = dt.datetime.now()
                        try:
                            subprocess.run(
                                [
                                    sys.executable,
                                    "-m",
                                    "hiper",
                                    "pause",
                                    "--duration",
                                    duration_input,
                                ],
                                check=False,
                            )
                        except KeyboardInterrupt:
                            pass
                        except (OSError, ValueError) as e:
                            print(f"Error running pause command: {e}")
                        resume_now = dt.datetime.now()
                        pause_dur_s = int(
                            (resume_now - pause_start_time).total_seconds()
                        )
                        print(
                            msgs.resuming_line(
                                _format_duration(pause_dur_s), resume_now
                            )
                        )
                        fd, old = _set_raw_mode()
                        paused = False
                        clock.resume()
                        pause_started = None
                        last_whole = -1
                        if getattr(args, "online", False) and nick:
                            storage.append_online_fokus_line(
                                nick, _online_fokus_line(args.title, comment)
                            )
                        is_first_render = True
                        _tick_render(
                            elapsed,
                            goal_override,
                            args.title,
                            is_first_render,
                            estimate_seconds,
                            time_worked_before,
                            context_time_before,
                            today_time_before,
                            online_status_line,
                        )
                        is_first_render = False
                        continue
                    else:
                        paused = True
                        pause_started = now
                        if getattr(args, "online", False) and nick:
                            storage.append_online_fokus_line(nick, "pause")
                        _finalize_render()
                        _restore_mode(fd, old)
                        fd, old = (None, None)
                        print(
                            msgs.paused_line(current_time=now, elapsed_seconds=elapsed)
                        )
                        continue
                else:
                    continue
            else:
                sys.stdout.write(msgs.command_prompt())
                sys.stdout.flush()
                line = sys.stdin.readline()
                if not line:
                    raise EOFError
                now = dt.datetime.now()
                cmd = line.strip()
                if cmd == "s":
                    _handle_save(args.title, start, now, elapsed, comment)
                    break
                is_save, title_override = _parse_save_command(cmd)
                if is_save:
                    save_title = (
                        title_override if title_override is not None else args.title
                    )
                    _handle_save(save_title, start, now, elapsed, comment)
                    break
                is_goal, new_duration, goal_error = _parse_goal_command(cmd)
                if is_goal:
                    if goal_error:
                        print(goal_error)
                        print(
                            msgs.paused_line(current_time=now, elapsed_seconds=elapsed)
                        )
                        continue
                    goal_override = new_duration
                    print(f"Goal updated to {new_duration}")
                    print(msgs.paused_line(current_time=now, elapsed_seconds=elapsed))
                    continue
                if cmd in ("help", "h", "?"):
                    print("Available commands while paused:")
                    print("  (enter), r, resume, continue  - Resume the session")
                    print("  s, save, save --title TITLE   - Save and end the session")
                    print(
                        "  goal DURATION                 - Change session goal (e.g., goal 5h)"
                    )
                    print("  d, discard, cancel            - Discard the session")
                    print("  h, help, ?                    - Show this help")
                    print(msgs.paused_line(current_time=now, elapsed_seconds=elapsed))
                    continue
                if cmd in ("cancel", "discard", "d"):
                    _finalize_render()
                    print(msgs.cancelled_line())
                    break
                if cmd in ("resume", "continue", "r", ""):
                    resume_now = dt.datetime.now()
                    if pause_started is not None:
                        pause_dur_s = int((resume_now - pause_started).total_seconds())
                    else:
                        pause_dur_s = 0
                    print("\x1b[1A\x1b[K", end="", flush=True)
                    print(msgs.resuming_line(_format_duration(pause_dur_s), resume_now))
                    fd, old = _set_raw_mode()
                    paused = False
                    clock.resume()
                    pause_started = None
                    last_whole = -1
                    if getattr(args, "online", False) and nick:
                        storage.append_online_fokus_line(
                            nick, _online_fokus_line(args.title, comment)
                        )
                    is_first_render = True
                    _tick_render(
                        elapsed,
                        goal_override,
                        args.title,
                        is_first_render,
                        estimate_seconds,
                        time_worked_before,
                        context_time_before,
                        today_time_before,
                        online_status_line,
                    )
                    is_first_render = False
                    continue
                if cmd:
                    print(msgs.paused_line(current_time=now, elapsed_seconds=elapsed))
                    continue
    except (KeyboardInterrupt, EOFError):
        _finalize_render()
        now = dt.datetime.now()
        elapsed = clock.seconds
        print(msgs.interrupted_line(elapsed_seconds=elapsed))
        return 130
    finally:
        _restore_mode(fd, old)
        _finalize_render()
        if wrote_online_fokus:
            storage.append_online_fokus_line(nick, "end")
    return 0


def get_command() -> Command:
    return Command(
        name="fokus",
        help="Start a focus session.",
        description="Start a focus session. Press Space to pause. When paused press Enter to resume, or type 'save (--title TITLE)' to save the session,  'goal DURATION' to change the session goal (e.g., goal 5h),  or 'discard' to discard the session. Use --strict to require pause duration when pausing.",
        configure_parser=fokus_configure_parser,
        run=fokus_run,
    )
