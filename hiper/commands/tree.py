"""Command-line workflows for hierarchical goals."""

import argparse
import datetime as dt

from .. import storage, trees
from ..timeutil import local_datetime, parse_duration
from . import Command, fokus


def configure_parser(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="tree_action")
    create = commands.add_parser("create", help="Create a tree; its root is its name")
    create.add_argument("name")
    create.add_argument("--estimate", default="")
    create.add_argument("--notes", default="", help="Associate a .md file")
    show = commands.add_parser("show", help="Show subtree totals since tree creation")
    show.add_argument("tree", nargs="?")
    for action, help_text in (
        ("add", "Add a child goal beneath a node"),
        ("set", "Change a node's name, estimate, or notes file"),
        ("focus", "Start focusing on a leaf or a group's General task"),
        ("log", "Record past focus time for a node"),
        ("notes", "Open a node's Markdown notes in VISUAL/EDITOR"),
        ("delete", "Delete a node and its descendants; keep sessions and notes"),
    ):
        sub = commands.add_parser(action, help=help_text)
        sub.add_argument("tree", help="Tree name")
        sub.add_argument(
            "node",
            nargs="?",
            default="/",
            help="Path relative to root, / for root, or node ID",
        )
        if action == "add":
            sub.add_argument("--name", required=True, help="New child's name")
            sub.add_argument("--estimate", default="")
            sub.add_argument("--notes", default="")
        elif action == "set":
            sub.add_argument("--name")
            sub.add_argument("--estimate", help="0s clears the estimate")
            sub.add_argument(
                "--notes", help="Markdown path; empty string restores default"
            )
        elif action == "focus":
            fokus.fokus_configure_parser(sub, include_title=False)
        elif action == "log":
            sub.add_argument("--duration", required=True)
            sub.add_argument(
                "--start", help="ISO datetime; default is now minus duration"
            )
            sub.add_argument("--comment", default="")
        elif action == "notes":
            sub.add_argument(
                "--path",
                action="store_true",
                help="Print notes path without opening or creating it",
            )


def _text(args: argparse.Namespace, key: str) -> str:
    value: object = getattr(args, key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    return value


def _optional(args: argparse.Namespace, key: str) -> str | None:
    value: object = getattr(args, key, None)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    return value


def run(args: argparse.Namespace) -> int:
    action = _optional(args, "tree_action") or "show"
    if action == "create":
        print(
            trees.create_tree(
                _text(args, "name"), _text(args, "estimate"), _text(args, "notes")
            )
        )
        return 0
    forest = trees.load_forest()
    if action == "show":
        tree = _optional(args, "tree")
        root = forest.resolve(tree) if tree else None
        totals = forest.totals(storage.load_sessions_csv())
        if not forest.roots:
            print("No trees. Create one with: hiper tree create NAME")
        for node, depth in forest.order:
            if root is not None and node.tree_id != root.id:
                continue
            print("  " * depth + ("- " if depth else "") + forest.label(node, totals))
            if not node.parent_id:
                print(
                    f"  Since {node.created_at.isoformat(sep=' ', timespec='seconds')}"
                )
        return 0
    node = forest.resolve(_text(args, "tree"), _text(args, "node"))
    if action == "add":
        print(
            trees.add_node(
                node.id,
                _text(args, "name"),
                _text(args, "estimate"),
                _text(args, "notes"),
            )
        )
    elif action == "set":
        print(
            trees.update_node(
                node.id,
                name=_optional(args, "name"),
                estimate=_optional(args, "estimate"),
                notes=_optional(args, "notes"),
            )
        )
    elif action == "delete":
        print(trees.delete_node(node.id))
    elif action == "notes":
        if args.path:
            print(trees.open_notes(node.id).path)
        else:
            return trees.edit_notes(node.id)
    elif action == "focus":
        target = trees.focus_target(node.id)
        args.title = target.title
        return fokus.fokus_run(args, tree_focus=target)
    elif action == "log":
        duration = parse_duration(_text(args, "duration"))
        if duration <= 0:
            raise ValueError("Duration must be greater than zero")
        start_text = _optional(args, "start")
        start = (
            local_datetime(start_text)
            if start_text
            else dt.datetime.now() - dt.timedelta(seconds=duration)
        )
        target = trees.focus_target(node.id)
        storage.save_session_csv(
            target.title,
            start,
            start + dt.timedelta(seconds=duration),
            duration,
            _text(args, "comment"),
            group=target.group,
            tree_id=target.tree_id,
            node_id=target.node_id,
        )
        print(f"Saved {storage.format_hms(duration)} to {target.group}")
    return 0


def get_command() -> Command:
    # Individual mutations lock internally; focus and editors must never hold a
    # data transaction open while waiting for user input.
    return Command(
        "tree",
        "Create and focus on trees of goals, with totals and notes",
        configure_parser,
        run,
    )
