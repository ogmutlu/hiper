import argparse
import os

from .. import config, storage
from .. import messages as msgs
from ..defaults import (
    DEFAULT_BAR_WIDTH,
    DEFAULT_CLOCK,
    DEFAULT_CLOCK_LENGTH,
    DEFAULT_COUNTDOWN,
    DEFAULT_ESTIMATE_BAR,
    DEFAULT_LANG,
    DEFAULT_NICK,
    DEFAULT_PAUSE_END_MUSIC,
    DEFAULT_PAUSE_LENGTH,
    DEFAULT_TODAY_TIME,
    DEFAULT_WORK_PER_DAY,
)
from . import Command


def set_configure_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument("--lang", help="Language code")
    p.add_argument("--nick", help="Your nickname")
    p.add_argument("--savedir", help="Directory to save sessions CSV (absolute path)")
    p.add_argument(
        "--clock",
        help="To show a loading bar use format 'bar=duration', e.g. --clock bar=1h15m. "
        "Otherwise use --clock digital or --clock dots",
    )
    p.add_argument(
        "--bar-width",
        type=int,
        help="Width of the progress bar (default: 42)",
    )
    p.add_argument(
        "--estimate-bar",
        help="Show estimate progress bar in fokus sessions (true/false)",
    )
    p.add_argument(
        "--work-per-day",
        help="Workable hours per day for planning (default: 8h)",
    )
    p.add_argument(
        "--countdown",
        help="Display countdown instead of target in estimate and clock bars (true/false)",
    )
    p.add_argument(
        "--pause-length",
        help="Default pause duration (e.g., 15m, 1h30m, 45s). Default: 15m",
    )
    p.add_argument(
        "--pause-end-music",
        help="MP3 file or folder to play when pause ends. Can be absolute path, or relative to data directory. If folder, plays random file.",
    )
    p.add_argument(
        "--today-time",
        help="Show total fokus time today in fokus sessions (true/false)",
    )
    p.add_argument("--show", action="store_true", help="Show current settings")


def set_run(args: argparse.Namespace) -> int:
    if args.show:
        lang = config.get_config("lang", DEFAULT_LANG)
        nick = config.get_config("nick", DEFAULT_NICK)
        savedir = config.get_data_dir()
        clock = config.get_config("clock", DEFAULT_CLOCK)
        bar_width = config.get_config("bar_width", DEFAULT_BAR_WIDTH)
        clock_length = config.get_config("clock_length", DEFAULT_CLOCK_LENGTH)
        estimate_bar = config.get_config("estimate_bar", DEFAULT_ESTIMATE_BAR)
        countdown = config.get_config("countdown", DEFAULT_COUNTDOWN)
        work_per_day = config.get_config("work_per_day", DEFAULT_WORK_PER_DAY)
        pause_length = config.get_config("pause_length", DEFAULT_PAUSE_LENGTH)
        pause_end_music = config.get_config("pause_end_music", DEFAULT_PAUSE_END_MUSIC)
        today_time = config.get_config("today_time", DEFAULT_TODAY_TIME)

        print("Current settings:")
        print(f"  lang: {lang}")
        print(f"  nick: {nick}")
        print(f"  savedir: {savedir}")
        print(f"  clock: {clock}")
        print(f"  bar_width: {bar_width}")
        print(f"  clock_length: {clock_length}")
        print(f"  estimate_bar: {estimate_bar}")
        print(f"  countdown: {countdown}")
        print(f"  work_per_day: {work_per_day}")
        print(f"  pause_length: {pause_length}")
        print(
            f"  pause_end_music: {pause_end_music if pause_end_music else '(not set)'}"
        )
        print(f"  today_time: {today_time}")
        return 0

    # Set values
    updated: list[str] = []
    pending: dict[str, str] = {}
    if args.lang is not None:
        lang = args.lang.strip().lower()
        pending["lang"] = lang

        updated.append(f"lang={lang}")

    if args.nick is not None:
        nick = args.nick.strip()
        pending["nick"] = nick
        updated.append(f"nick={nick}")

    if args.savedir is not None:
        savedir = args.savedir.strip()
        if not os.path.isabs(savedir):
            print(f"Error: savedir must be an absolute path: {savedir}")
            return 1
        if os.path.exists(savedir) and not os.path.isdir(savedir):
            raise ValueError(f"savedir is not a directory: {savedir}")
        pending["savedir"] = savedir
        updated.append(f"savedir={savedir}")

    if args.clock is not None:
        clock_parts = args.clock.strip().lower().split("=")
        if len(clock_parts) > 2:
            raise ValueError("clock must be digital, dots, or bar=DURATION")
        clock = clock_parts[0]
        if clock not in ("digital", "dots", "bar"):
            print(f"Error: invalid clock value: {clock}")
            return 1
        pending["clock"] = clock
        if len(clock_parts) > 1:
            length_str = clock_parts[1]
            try:
                # Validate the duration format
                if clock != "bar" or storage.parse_duration(length_str) <= 0:
                    raise ValueError("bar clock duration must be greater than zero")
                pending["clock_length"] = length_str
                updated.append(f"clock_length={length_str}")
            except ValueError as e:
                print(f"Error: invalid clock length '{length_str}': {e}")
                return 1
        updated.append(f"clock={clock}")

    if args.bar_width is not None:
        if args.bar_width <= 0:
            print(f"Error: bar_width must be > 0: {args.bar_width}")
            return 1
        pending["bar_width"] = str(args.bar_width)
        updated.append(f"bar_width={args.bar_width}")

    if args.estimate_bar is not None:
        estimate_bar = args.estimate_bar.strip().lower()
        if estimate_bar not in ("true", "false"):
            print(f"Error: estimate_bar must be 'true' or 'false': {estimate_bar}")
            return 1
        pending["estimate_bar"] = estimate_bar
        updated.append(f"estimate_bar={estimate_bar}")

    if args.countdown is not None:
        countdown = args.countdown.strip().lower()
        if countdown not in ("true", "false"):
            print(f"Error: countdown must be 'true' or 'false': {countdown}")
            return 1
        pending["countdown"] = countdown
        updated.append(f"countdown={countdown}")

    if args.work_per_day is not None:
        work_per_day = args.work_per_day.strip()
        try:
            seconds = storage.parse_duration(work_per_day)
            if seconds <= 0:
                raise ValueError("must be greater than zero")
        except (OSError, ValueError) as e:
            print(f"Error: invalid work-per-day '{work_per_day}': {e}")
            return 1
        # Store original string so display matches user intent.
        pending["work_per_day"] = work_per_day
        updated.append(f"work_per_day={work_per_day}")

    if args.pause_length is not None:
        pause_length = args.pause_length.strip()
        try:
            seconds = storage.parse_duration(pause_length)
            if seconds <= 0:
                raise ValueError("must be greater than zero")
        except (OSError, ValueError) as e:
            print(f"Error: invalid pause-length '{pause_length}': {e}")
            return 1
        # Store original string so display matches user intent.
        pending["pause_length"] = pause_length
        updated.append(f"pause_length={pause_length}")

    if args.pause_end_music is not None:
        pause_end_music = args.pause_end_music.strip()
        # Allow empty string to disable music
        if pause_end_music:
            # Resolve path: if absolute, use as-is; if relative, join with data dir
            data_dir = pending.get("savedir", config.get_data_dir())
            if os.path.isabs(pause_end_music):
                music_path = pause_end_music
            else:
                music_path = os.path.join(data_dir, pause_end_music)

            if not os.path.exists(music_path):
                print(f"Error: music file or folder not found: {music_path}")
                return 1

            # If it's a file, it should be .mp3; if it's a directory, that's fine
            if os.path.isfile(music_path) and not pause_end_music.lower().endswith(
                ".mp3"
            ):
                print(f"Error: music file must be a .mp3 file: {pause_end_music}")
                return 1
        pending["pause_end_music"] = pause_end_music
        updated.append(
            f"pause_end_music={pause_end_music if pause_end_music else '(empty)'}"
        )

    if args.today_time is not None:
        today_time = args.today_time.strip().lower()
        if today_time not in ("true", "false"):
            print(f"Error: today_time must be 'true' or 'false': {today_time}")
            return 1
        pending["today_time"] = today_time
        updated.append(f"today_time={today_time}")

    if updated:
        if "savedir" in pending:
            os.makedirs(pending["savedir"], exist_ok=True)
        config.update_config(pending)
        if "lang" in pending:
            msgs.set_language(pending["lang"])
        print(f"Updated: {', '.join(updated)}")
    else:
        print("No settings specified. Use --show to see current settings.")
        print(
            "Available options: --lang, --nick, --savedir, --clock, --bar-width, "
            "--estimate-bar, --countdown, --work-per-day, --pause-length, --pause-end-music, --today-time"
        )

    return 0


def get_command() -> Command:
    return Command(
        name="set",
        help="Set configuration options.",
        description="Set configuration options like language, "
        "nickname, save directory, etc.",
        configure_parser=set_configure_parser,
        run=set_run,
    )
