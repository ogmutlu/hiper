"""Tree browsing, editing forms, and Markdown notes widgets."""

from collections.abc import Awaitable, Callable
from typing import ClassVar, override

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, Tab, TabPane, Tabs, TextArea, Tree
from textual.widgets.tree import TreeNode

from .. import trees
from ..timeutil import format_hms


class TaskTree(Tree[str]):
    def __init__(self) -> None:
        super().__init__("Trees", id="task-tree")
        self.last_clicked_node: str | None = None

    @override
    async def _on_click(self, event: events.Click) -> None:
        event.prevent_default()
        event.stop()
        if event.style.meta.get("toggle", False):
            self.last_clicked_node = None
            await super()._on_click(event)
            return
        line: object = event.style.meta.get("line")
        if not isinstance(line, int):
            return
        node = self.get_node_at_line(line)
        if node is None:
            return
        self.cursor_line = line
        if event.chain == 2 and node.data == self.last_clicked_node:
            await super()._on_click(event)
        self.last_clicked_node = node.data


class TreePane(TabPane):
    class FocusRequested(Message):
        def __init__(self, identifier: str) -> None:
            super().__init__()
            self.identifier = identifier

    class NotesRequested(Message):
        def __init__(self, identifier: str) -> None:
            super().__init__()
            self.identifier = identifier

    class DeleteRequested(Message):
        def __init__(self, identifier: str, description: str) -> None:
            super().__init__()
            self.identifier = identifier
            self.description = description

    class MutationRequested(Message):
        def __init__(self, operation: Callable[[], str]) -> None:
            super().__init__()
            self.operation = operation

    def __init__(self) -> None:
        super().__init__("Trees  F2", id="trees")
        self.forest = trees.TaskForest([])
        self.selected_id: str | None = None
        self.busy = False
        self.node_widgets: dict[str, TreeNode[str]] = {}
        self.active_tree_id: str | None = None
        self.tree_selections: dict[str, str] = {}
        self.expanded_nodes: set[str] = set()
        self.known_nodes: set[str] = set()
        self.totals: dict[str, int] = {}

    @override
    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(
                "Goals, from the whole to the next step", classes="section-title"
            )
            yield Static(
                "Click to select; double-click a name or press Enter to focus. Space folds a group. Totals include all descendants.",
                classes="hint",
                markup=False,
            )
            yield Tabs(id="tree-tabs")
            yield TaskTree()
            yield Static(
                "Create a tree to get started.", id="tree-selection", markup=False
            )
            with Horizontal(classes="buttons"):
                yield Button("Focus", id="tree-focus", variant="primary")
                yield Button("Open notes", id="tree-notes")
                yield Button("Delete subtree", id="tree-delete", variant="error")
            yield Static("NEW TREE", classes="eyebrow")
            yield Input(placeholder="Tree name", id="tree-name")
            yield Button("Create tree", id="tree-create")
            yield Static("ADD CHILD TO SELECTED NODE", classes="eyebrow")
            yield Input(placeholder="Child goal name", id="tree-child-name")
            yield Input(
                placeholder="Optional estimate, e.g. 2h", id="tree-child-estimate"
            )
            yield Button("Add child", id="tree-add")
            yield Static("EDIT SELECTED NODE", classes="eyebrow")
            yield Input(placeholder="Node name", id="tree-node-name")
            yield Input(
                placeholder="Estimate, e.g. 4h; blank clears", id="tree-estimate"
            )
            yield Input(
                placeholder="Optional .md path; blank uses managed notes",
                id="tree-notes-path",
            )
            yield Button("Save node", id="tree-update")

    async def render_forest(
        self, forest: trees.TaskForest, totals: dict[str, int]
    ) -> None:
        self._remember_view()
        self.forest = forest
        self.totals = totals
        roots = {root.id for root in forest.roots}
        if self.active_tree_id not in roots:
            self.active_tree_id = forest.roots[0].id if forest.roots else None
        tabs = self.query_one("#tree-tabs", Tabs)
        with tabs.prevent(Tabs.TabActivated):
            await tabs.clear()
            for root in forest.roots:
                await tabs.add_tab(Tab(Text(root.name), id=f"tree-tab-{root.id}"))
            tabs.active = (
                f"tree-tab-{self.active_tree_id}" if self.active_tree_id else ""
            )
        tabs.display = bool(roots)
        self._render_tree()

    def _remember_view(self) -> None:
        for identifier, widget in self.node_widgets.items():
            if widget.is_expanded:
                self.expanded_nodes.add(identifier)
            else:
                self.expanded_nodes.discard(identifier)
        if self.active_tree_id and self.selected_id:
            self.tree_selections[self.active_tree_id] = self.selected_id

    def _render_tree(self) -> None:
        tree = self.query_one(TaskTree)
        root = self.forest.by_id.get(self.active_tree_id or "")
        widgets: dict[str, TreeNode[str]] = {}
        if root is None:
            tree.reset(Text("Create a tree to get started"))
            self.selected_id = None
            self.query_one("#tree-selection", Static).update(
                "Create a tree to get started."
            )
            for field in ("tree-node-name", "tree-estimate", "tree-notes-path"):
                self.query_one(f"#{field}", Input).value = ""
        else:
            tree.reset(Text(self.forest.label(root, self.totals)), root.id)
            if root.id in self.expanded_nodes or root.id not in self.known_nodes:
                tree.root.expand()
            else:
                tree.root.collapse()
            widgets[root.id] = tree.root
            for node in self.forest.subtree(root.id):
                if node.id == root.id:
                    continue
                widgets[node.id] = widgets[node.parent_id].add(
                    Text(self.forest.label(node, self.totals)),
                    data=node.id,
                    expand=node.id in self.expanded_nodes
                    or node.id not in self.known_nodes,
                    allow_expand=bool(self.forest.children.get(node.id)),
                )
            self.selected_id = self.tree_selections.get(root.id, root.id)
            if self.selected_id not in widgets:
                self.selected_id = root.id
        self.node_widgets = widgets
        self.known_nodes.update(widgets)
        if self.selected_id in widgets:
            self.call_after_refresh(tree.move_cursor, widgets[self.selected_id])
        self.set_busy(self.busy)

    @on(Tabs.TabActivated, "#tree-tabs")
    def switch_tree(self, event: Tabs.TabActivated) -> None:
        event.stop()
        identifier = (event.tab.id or "").removeprefix("tree-tab-")
        if identifier == self.active_tree_id or identifier not in self.forest.by_id:
            return
        self._remember_view()
        self.active_tree_id = identifier
        self._render_tree()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.query_one("#tree-tabs", Tabs).disabled = busy
        for button in self.query(Button):
            button.disabled = busy or (
                button.id != "tree-create" and self.selected_id is None
            )

    @on(Tree.NodeHighlighted, "#task-tree")
    def highlight(self, event: Tree.NodeHighlighted[str]) -> None:
        identifier = event.node.data
        # Ignore queued highlights from the tree that was just replaced.
        if (
            identifier not in self.node_widgets
            or self.node_widgets[identifier] is not event.node
        ):
            return
        self.selected_id = identifier if identifier in self.forest.by_id else None
        if self.selected_id is not None:
            node = self.forest.require(self.selected_id)
            root = self.forest.require(node.tree_id)
            self.query_one("#tree-selection", Static).update(
                f"{self.forest.path(node.id)} · Since {root.created_at:%Y-%m-%d %H:%M}"
            )
            self.query_one("#tree-node-name", Input).value = node.name
            self.query_one("#tree-estimate", Input).value = (
                format_hms(node.estimate_seconds) if node.estimate_seconds else ""
            )
            self.query_one("#tree-notes-path", Input).value = node.notes_path
        else:
            self.query_one("#tree-selection", Static).update(
                "Select a node with the arrow keys, or create a tree."
            )
        self.set_busy(self.busy)

    @on(Tree.NodeSelected, "#task-tree")
    def start_node(self, event: Tree.NodeSelected[str]) -> None:
        event.stop()
        if not self.busy and event.node.data in self.forest.by_id:
            self.post_message(
                self.FocusRequested(self.forest.require(event.node.data or "").id)
            )

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        event.stop()
        if self.busy:
            return
        button = event.button.id
        if button == "tree-create":
            name = self.query_one("#tree-name", Input).value
            self.post_message(self.MutationRequested(lambda: trees.create_tree(name)))
            return
        identifier = self.selected_id
        if identifier is None:
            return
        if button == "tree-add":
            child = self.query_one("#tree-child-name", Input).value
            estimate = self.query_one("#tree-child-estimate", Input).value
            self.post_message(
                self.MutationRequested(
                    lambda: trees.add_node(identifier, child, estimate)
                )
            )
        elif button == "tree-update":
            name = self.query_one("#tree-node-name", Input).value
            estimate = self.query_one("#tree-estimate", Input).value
            notes = self.query_one("#tree-notes-path", Input).value
            self.post_message(
                self.MutationRequested(
                    lambda: trees.update_node(
                        identifier, name=name, estimate=estimate, notes=notes
                    )
                )
            )
        elif button == "tree-focus":
            self.post_message(self.FocusRequested(identifier))
        elif button == "tree-notes":
            self.post_message(self.NotesRequested(identifier))
        elif button == "tree-delete":
            self.post_message(
                self.DeleteRequested(identifier, self.forest.path(identifier))
            )


class NotesEditor(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self, document: trees.NotesDocument, save: Callable[[str], Awaitable[None]]
    ) -> None:
        super().__init__()
        self.document = document
        self.save = save
        self.saving = False

    @override
    def compose(self) -> ComposeResult:
        with Vertical(id="notes-dialog"):
            yield Static(str(self.document.path), id="notes-file", markup=False)
            yield TextArea(self.document.text, id="notes-text", soft_wrap=True)
            yield Static(
                "Markdown notes · Cancel leaves the file unchanged",
                id="notes-status",
                markup=False,
            )
            with Horizontal(classes="buttons"):
                yield Button("Save notes", id="notes-save", variant="primary")
                yield Button("Cancel", id="notes-cancel")

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    def action_cancel(self) -> None:
        if not self.saving:
            self.dismiss(None)

    @on(Button.Pressed)
    async def choose(self, event: Button.Pressed) -> None:
        event.stop()
        if self.saving:
            return
        if event.button.id == "notes-cancel":
            self.action_cancel()
            return
        self.saving = True
        save_button = self.query_one("#notes-save", Button)
        save_button.disabled = True
        try:
            await self.save(self.query_one(TextArea).text)
        except (OSError, ValueError) as exc:
            self.query_one("#notes-status", Static).update(str(exc))
        else:
            self.dismiss(None)
        finally:
            self.saving = False
            save_button.disabled = False
