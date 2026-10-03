import argparse
import sys
from contextlib import nullcontext

from .commands import COMMAND_REGISTRY, load_builtin_commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hiper",
        description="hiper - a tiny, extensible terminal helper",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    load_builtin_commands()

    # Dynamically add subparsers from the registry
    for command_name, command in COMMAND_REGISTRY.items():
        sub = subparsers.add_parser(
            command_name,
            help=command.help,
            description=command.description or command.help,
        )
        command.configure_parser(sub)

    parser.add_argument(
        "--list",
        action="store_true",
        help="List available commands and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    if not argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)

    if getattr(args, "list", False):
        print("Available commands:")
        for name in sorted(COMMAND_REGISTRY.keys()):
            print(f"  {name}")
        return 0

    command_value: object = getattr(args, "command", None)
    cmd_name = command_value if isinstance(command_value, str) else None
    if not cmd_name:
        parser.print_help()
        return 0

    command = COMMAND_REGISTRY.get(cmd_name)
    if not command:
        print(f"Unknown command: {cmd_name}", file=sys.stderr)
        return 2

    try:
        from . import messages
        from .config import get_config
        from .defaults import DEFAULT_LANG

        messages.set_language(get_config("lang", DEFAULT_LANG))
        from .storage import data_transaction

        with data_transaction() if command.mutates(args) else nullcontext():
            return command.run(args)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
