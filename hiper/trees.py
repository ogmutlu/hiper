"""Task trees, subtree accounting, and Markdown notes shared by CLI and TUI."""

import datetime as dt
import os
import shlex
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from . import storage
from .files import atomic_text_writer
from .models import Session, TaskNode
from .timeutil import format_hms, parse_duration


def _name(value: str) -> str:
    value = value.strip()
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError(
            "Node names must be nonempty and cannot contain / or control characters"
        )
    return value


def _estimate(value: str) -> int:
    seconds = parse_duration(value) if value.strip() else 0
    if seconds < 0:
        raise ValueError("Estimate must be nonnegative")
    return seconds


def _notes_path(value: str) -> str:
    if not value.strip():
        return ""
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != ".md" or path.is_dir():
        raise ValueError("Notes must be a Markdown (.md) file")
    return str(path)


class TaskForest:
    """Validated forest with stable identities and unambiguous sibling paths."""

    def __init__(self, nodes: Sequence[TaskNode]) -> None:
        self.nodes = tuple(nodes)
        self.by_id: dict[str, TaskNode] = {}
        self.children: dict[str, list[TaskNode]] = {}
        siblings: set[tuple[str, str]] = set()
        for node in nodes:
            if (
                not node.id
                or node.id in self.by_id
                or any(
                    c
                    not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                    for c in node.id
                )
            ):
                raise ValueError("trees.csv: invalid or duplicate node ID")
            if _name(node.name) != node.name or node.estimate_seconds < 0:
                raise ValueError("trees.csv: invalid node name or estimate")
            if node.notes_path and (
                not Path(node.notes_path).is_absolute()
                or Path(node.notes_path).suffix.lower() != ".md"
            ):
                raise ValueError("trees.csv: notes path must be an absolute .md path")
            key = (node.parent_id, node.name)
            if key in siblings:
                raise ValueError(f"Duplicate sibling/tree name: {node.name}")
            siblings.add(key)
            self.by_id[node.id] = node
            self.children.setdefault(node.parent_id, []).append(node)
        self.roots = tuple(self.children.get("", []))
        for node in nodes:
            root = self.by_id.get(node.tree_id)
            parent = self.by_id.get(node.parent_id)
            if root is None or root.parent_id or root.tree_id != root.id:
                raise ValueError("trees.csv: invalid tree root")
            if node.parent_id and (parent is None or parent.tree_id != node.tree_id):
                raise ValueError("trees.csv: missing parent or parent in another tree")
        self.order: list[tuple[TaskNode, int]] = []
        stack = [(root, 0) for root in reversed(self.roots)]
        while stack:
            node, depth = stack.pop()
            self.order.append((node, depth))
            stack.extend(
                (child, depth + 1) for child in reversed(self.children.get(node.id, []))
            )
        if len(self.order) != len(nodes):
            raise ValueError("trees.csv: cycle or unreachable node")

    def require(self, identifier: str) -> TaskNode:
        node = self.by_id.get(identifier)
        if node is None:
            raise ValueError("Node no longer exists; refresh and select a node")
        return node

    def resolve(self, tree: str, path: str = "/") -> TaskNode:
        roots = [root for root in self.roots if root.name == tree or root.id == tree]
        if len(roots) != 1:
            raise ValueError(f"Tree not found or ambiguous: {tree}")
        node = roots[0]
        if path in self.by_id and self.by_id[path].tree_id == node.id:
            return self.by_id[path]
        for part in path.strip("/").split("/") if path.strip("/") else []:
            child = next(
                (
                    child
                    for child in self.children.get(node.id, [])
                    if child.name == part
                ),
                None,
            )
            if child is None:
                raise ValueError(f"Node not found: {tree}/{path.strip('/')}")
            node = child
        return node

    def path(self, identifier: str) -> str:
        node = self.require(identifier)
        parts = [node.name]
        while node.parent_id:
            node = self.require(node.parent_id)
            parts.append(node.name)
        return "/".join(reversed(parts))

    def subtree(self, identifier: str) -> Iterator[TaskNode]:
        stack = [self.require(identifier)]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(self.children.get(node.id, [])))

    def totals(self, sessions: Sequence[Session]) -> dict[str, int]:
        totals = dict.fromkeys(self.by_id, 0)
        for session in sessions:
            node = self.by_id.get(session["node_id"])
            if node is None or node.tree_id != session["tree_id"]:
                continue
            if session["start"] >= self.by_id[node.tree_id].created_at:
                totals[node.id] += session["duration"]
        for node, _ in reversed(self.order):
            if node.parent_id:
                totals[node.parent_id] += totals[node.id]
        return totals

    def label(self, node: TaskNode, totals: dict[str, int]) -> str:
        label = f"{node.name}  {format_hms(totals[node.id])}"
        if node.estimate_seconds:
            label += f" / {format_hms(node.estimate_seconds)}"
        return label


def load_forest() -> TaskForest:
    return TaskForest(storage.load_tree_nodes_csv())


def create_tree(name: str, estimate: str = "", notes: str = "") -> str:
    with storage.data_transaction():
        forest = load_forest()
        identifier = uuid4().hex
        node = TaskNode(
            identifier,
            identifier,
            "",
            _name(name),
            dt.datetime.now(),
            _estimate(estimate),
            _notes_path(notes),
        )
        nodes = [*forest.nodes, node]
        TaskForest(nodes)
        storage.save_tree_nodes_csv(nodes)
    return f"Created tree {node.name}"


def add_node(parent_id: str, name: str, estimate: str = "", notes: str = "") -> str:
    with storage.data_transaction():
        forest = load_forest()
        parent = forest.require(parent_id)
        node = TaskNode(
            uuid4().hex,
            parent.tree_id,
            parent.id,
            _name(name),
            dt.datetime.now(),
            _estimate(estimate),
            _notes_path(notes),
        )
        nodes = [*forest.nodes, node]
        TaskForest(nodes)
        storage.save_tree_nodes_csv(nodes)
    return f"Added {node.name} under {parent.name}"


def update_node(
    identifier: str,
    *,
    estimate: str | None = None,
    notes: str | None = None,
    name: str | None = None,
) -> str:
    with storage.data_transaction():
        forest = load_forest()
        node = forest.require(identifier)
        updated = replace(
            node,
            name=_name(name) if name is not None else node.name,
            estimate_seconds=_estimate(estimate)
            if estimate is not None
            else node.estimate_seconds,
            notes_path=_notes_path(notes) if notes is not None else node.notes_path,
        )
        nodes = []
        for item in forest.nodes:
            replacement = updated if item.id == identifier else item
            # Retain an existing notes file when its tree or node is renamed.
            # An explicitly supplied nonempty notes path takes precedence.
            renamed = updated.name != node.name and (
                item.id == identifier
                or (not node.parent_id and item.tree_id == identifier)
            )
            old_path = _managed_notes_path(forest, item)
            if (
                renamed
                and not item.notes_path
                and not replacement.notes_path
                and old_path.exists()
            ):
                replacement = replace(replacement, notes_path=str(old_path))
            nodes.append(replacement)
        TaskForest(nodes)
        storage.save_tree_nodes_csv(nodes)
    return f"Updated {updated.name}"


def delete_node(identifier: str) -> str:
    with storage.data_transaction():
        forest = load_forest()
        node = forest.require(identifier)
        removed = {item.id for item in forest.subtree(identifier)}
        storage.save_tree_nodes_csv(
            [item for item in forest.nodes if item.id not in removed]
        )
    return f"Deleted {node.name} and {len(removed) - 1} descendants; sessions and notes retained"


@dataclass(frozen=True, slots=True)
class TreeFocus:
    title: str
    group: str
    tree_id: str
    node_id: str


def focus_target(identifier: str) -> TreeFocus:
    forest = load_forest()
    node = forest.require(identifier)
    title = (
        "General" if forest.children.get(node.id) or not node.parent_id else node.name
    )
    return TreeFocus(title, forest.path(node.id), node.tree_id, node.id)


@dataclass(frozen=True, slots=True)
class NotesDocument:
    path: Path
    text: str
    original: str | None


def _managed_notes_path(forest: TaskForest, node: TaskNode) -> Path:
    root = forest.require(node.tree_id)
    filename = f"{root.name} - {node.name}.md" if node.parent_id else f"{root.name}.md"
    return (Path(storage.get_data_dir()) / "notes" / filename).resolve()


def open_notes(identifier: str) -> NotesDocument:
    forest = load_forest()
    node = forest.require(identifier)
    path = (
        Path(node.notes_path) if node.notes_path else _managed_notes_path(forest, node)
    ).resolve()
    original = path.read_text(encoding="utf-8") if path.exists() else None
    text = original if original is not None else f"# {node.name}\n\n"
    legacy = Path(storage.get_data_dir()) / "notes" / f"{node.id}.md"
    if original is None and not node.notes_path and legacy.exists():
        text = legacy.read_text(encoding="utf-8")
    return NotesDocument(path, text, original)


def save_notes(document: NotesDocument, text: str) -> str:
    with storage.data_transaction():
        current = (
            document.path.read_text(encoding="utf-8")
            if document.path.exists()
            else None
        )
        if current != document.original:
            raise ValueError(
                "Notes changed on disk; copy your edits and reopen before saving"
            )
        with atomic_text_writer(document.path) as stream:
            stream.write(text)
    return f"Saved notes: {document.path}"


def edit_notes(identifier: str) -> int:
    document = open_notes(identifier)
    command = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi")
    if not command:
        raise ValueError("VISUAL/EDITOR must contain an editor command")
    if document.original is None:
        save_notes(document, document.text)
    return subprocess.run([*command, str(document.path)], check=False).returncode
