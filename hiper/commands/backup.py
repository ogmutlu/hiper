import argparse
import datetime as dt
import os
import shutil

from .. import config
from . import Command


def backup_configure_parser(p: argparse.ArgumentParser) -> None:
    # No extra arguments for now; always backs up the configured data_dir.
    return None


def _build_backup_path(data_dir: str) -> str:
    """Return backup path alongside data_dir with timestamp suffix."""
    timestamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    return os.path.join(data_dir, f"backup_{timestamp}")


def _ignore_backup_dirs(_dir: str, names: list[str]) -> list[str]:
    """Ignore any directories that start with backup_ to avoid nested backups."""
    return [name for name in names if name.startswith("backup_")]


def backup_run(_args: argparse.Namespace) -> int:
    data_dir = config.get_data_dir()
    if not os.path.exists(data_dir):
        print(f"Error: data_dir '{data_dir}' does not exist")
        return 1

    backup_path = _build_backup_path(data_dir)

    try:
        shutil.copytree(data_dir, backup_path, ignore=_ignore_backup_dirs)
    except FileExistsError:
        print(f"Error: backup path already exists: {backup_path}")
        return 1
    except OSError as e:  # pragma: no cover - unexpected errors
        print(f"Error: failed to create backup: {e}")
        return 1

    print(f"Backup created at {backup_path}")
    return 0


def get_command() -> Command:
    return Command(
        name="backup",
        help="Backup hiper data directory.",
        description="Copy the hiper data directory to a backup subdirectory with a "
        "timestamp suffix.",
        configure_parser=backup_configure_parser,
        run=backup_run,
        mutates=lambda args: True,
    )
