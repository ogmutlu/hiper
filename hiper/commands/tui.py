import argparse
import sys

from . import Command


def tui_configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title", help="Prefill the focus session title", default="")


def tui_run(args: argparse.Namespace) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("tui requires an interactive terminal")
    from ..tui.app import HiperApp

    HiperApp(focus_title=str(args.title)).run()
    return 0


def get_command() -> Command:
    return Command(
        name="tui",
        help="Open the interactive terminal interface.",
        configure_parser=tui_configure_parser,
        run=tui_run,
    )
