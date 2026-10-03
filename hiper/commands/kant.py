import argparse
import os
import random

from .. import storage
from . import Command


def kant_configure_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--title",
        "-t",
        help="Title of the .md file to read from (default: kant)",
    )


def kant_run(args: argparse.Namespace) -> int:
    data_dir = storage.get_data_dir()

    # Determine which file to read
    if args.title:
        filename = f"{args.title.strip()}.md"
    else:
        filename = "kant.md"

    file_path = os.path.join(data_dir, filename)

    if not os.path.exists(file_path):
        print(f"Error: {filename} not found in {data_dir}")
        print(f"Please create {filename} file in the data directory.")
        return 1

    try:
        with open(file_path, encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        if not lines:
            print(f"Error: {filename} is empty")
            return 1

        # Pick a random line
        random_line = random.choice(lines)
        print(random_line)
        return 0

    except (OSError, UnicodeError) as e:
        print(f"Error reading {filename}: {e}")
        return 1


def get_command() -> Command:
    return Command(
        name="kant",
        help="Display a random line from a .md file",
        description="Display a random line from kant.md (default) or TITLE.md (with --title) "
        "file in the data directory.",
        configure_parser=kant_configure_parser,
        run=kant_run,
    )
