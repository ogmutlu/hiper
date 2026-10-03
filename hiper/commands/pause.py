import argparse
import datetime as dt
import math
import os
import random
import subprocess
import sys
import time

from .. import config, storage
from ..defaults import (
    DEFAULT_COUNTDOWN,
    DEFAULT_PAUSE_END_MUSIC,
    DEFAULT_PAUSE_LENGTH,
)
from . import Command


def pause_configure_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--duration",
        "-d",
        help="Duration of the pause (e.g., 15m, 1h30m, 45s). "
        f"Defaults to pause_length config (default: {DEFAULT_PAUSE_LENGTH})",
    )
    p.add_argument(
        "--music",
        "-m",
        help="Music file or folder to play when pause ends (overrides pause_end_music config). "
        "Can be absolute path, or relative to data directory. If folder, plays random file.",
    )
    p.add_argument(
        "--no-music",
        action="store_true",
        help="Disable music for this pause session (overrides pause_end_music config).",
    )


def pause_run(args: argparse.Namespace) -> int:
    # Get duration from argument or config
    duration_str = args.duration
    if duration_str is None:
        duration_str = config.get_config("pause_length", DEFAULT_PAUSE_LENGTH)

    try:
        duration_seconds = storage.parse_duration(duration_str)
    except ValueError as e:
        print(f"Error: invalid duration '{duration_str}': {e}", file=sys.stderr)
        return 1

    start_time = dt.datetime.now()
    end_time = start_time + dt.timedelta(seconds=duration_seconds)
    formatted_duration = storage.format_hms(duration_seconds)

    # Check if countdown is enabled
    countdown_enabled = (
        config.get_config("countdown", DEFAULT_COUNTDOWN).lower() == "true"
    )

    print(f"Pause started: {start_time.strftime('%H:%M:%S')}")
    print(f"Duration: {formatted_duration}")
    print(f"Will end at: {end_time.strftime('%H:%M:%S')}")

    # Wait for the duration with optional countdown
    deadline = time.monotonic() + duration_seconds
    try:
        if countdown_enabled:
            # Show countdown timer
            remaining_seconds = duration_seconds
            while remaining_seconds > 0:
                remaining_formatted = storage.format_hms(remaining_seconds)
                print(
                    f"\rRemaining: {remaining_formatted} (Press Ctrl+C to interrupt)",
                    end="",
                    flush=True,
                )
                time.sleep(1)
                remaining_seconds = max(0, math.ceil(deadline - time.monotonic()))
            print()  # New line after countdown completes
        else:
            print("Waiting... Press Ctrl+C to interrupt", end="", flush=True)
            time.sleep(duration_seconds)
            print()  # New line after sleep
    except KeyboardInterrupt:
        if countdown_enabled:
            print("\nPause discarded")
        else:
            print("\nPause discarded")
        print("---------------------------------")
        return 130

    end_time = dt.datetime.now()
    # Signal the end of the pause
    print("\nPAUSE ENDED!")
    print(f"Started at: {start_time.strftime('%H:%M:%S')}")
    print(f"Ended at: {end_time.strftime('%H:%M:%S')}")
    print(f"Duration: {formatted_duration}")

    # Get pause end configuration
    # --no-music takes priority, then --music, then config
    if args.no_music:
        pause_end_music = ""
    else:
        pause_end_music = (
            args.music
            if args.music
            else config.get_config("pause_end_music", DEFAULT_PAUSE_END_MUSIC)
        )

    # Check if music is configured
    use_music = pause_end_music and pause_end_music.strip()

    if not use_music:
        # No alarm configured
        print("---------------------------------")
        return 0

    print("Press Ctrl+C to stop the alarm...")

    if use_music:
        # Resolve music path: if absolute, use as-is; if relative, join with data dir
        data_dir = storage.get_data_dir()
        music_input = pause_end_music.strip()
        if os.path.isabs(music_input):
            music_path = music_input
        else:
            music_path = os.path.join(data_dir, music_input)

        if not os.path.exists(music_path):
            print(
                f"Error: music file or folder not found: {music_path}", file=sys.stderr
            )
            print("---------------------------------")
            return 0

        # If it's a directory, pick a random file from it
        if os.path.isdir(music_path):
            # Get all files in the directory
            files = [
                f
                for f in os.listdir(music_path)
                if f.lower().endswith(".mp3")
                and os.path.isfile(os.path.join(music_path, f))
            ]
            if not files:
                print(
                    f"Error: no files found in directory: {music_path}", file=sys.stderr
                )
                print("---------------------------------")
                return 0
            # Pick a random file
            selected_file = random.choice(files)
            music_path = os.path.join(music_path, selected_file)
        # If it's a file, use it directly

        # Check if VLC is available
        try:
            subprocess.run(
                ["vlc", "--version"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print(
                "Error: VLC not found. Please install VLC media player.",
                file=sys.stderr,
            )
            print("---------------------------------")
            return 0

        try:
            # Play music once with VLC until file ends or user interrupts
            subprocess.run(
                ["vlc", "--intf", "dummy", "--play-and-exit", music_path],
                check=False,
                timeout=None,  # Let it play fully
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except KeyboardInterrupt:
            # Clear the line to hide ^C
            print("\r\033[K", end="", flush=True)
        except Exception as e:
            print(f"Error playing music: {e}", file=sys.stderr)

    print("---------------------------------")
    return 0


def get_command() -> Command:
    return Command(
        name="pause",
        help="Set a pause timer with an alarm.",
        description="Set a pause timer for a specified duration. "
        "When the pause ends, an alarm will signal the end.",
        configure_parser=pause_configure_parser,
        run=pause_run,
    )
