import argparse
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    help: str
    configure_parser: Callable[[argparse.ArgumentParser], None]
    run: Callable[[argparse.Namespace], int]
    description: str | None = None
    mutates: Callable[[argparse.Namespace], bool] = lambda args: False


COMMAND_REGISTRY: dict[str, Command] = {}


def register_command(cmd: Command) -> None:
    COMMAND_REGISTRY[cmd.name] = cmd


def load_builtin_commands() -> None:
    """Load all builtin commands into the registry."""
    from . import (
        backup,
        delete,
        finish,
        fokus,
        kant,
        log,
        loop,
        pause,
        postfokus,
        prefokus,
        read,
        set,
        tui,
    )

    register_command(backup.get_command())
    register_command(delete.get_command())
    register_command(finish.get_command())
    register_command(fokus.get_command())
    register_command(kant.get_command())
    register_command(log.get_command())
    register_command(loop.get_command())
    register_command(pause.get_command())
    register_command(postfokus.get_command())
    register_command(prefokus.get_command())
    register_command(read.get_command())
    register_command(set.get_command())
    register_command(tui.get_command())
