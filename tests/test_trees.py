import csv
import datetime as dt
from dataclasses import replace
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase, mock

from textual.widgets import Button, Input, TabbedContent, Tabs, TextArea

from hiper import storage, trees
from hiper.commands import fokus
from hiper.models import TaskNode
from hiper.tui import services
from hiper.tui.app import DeleteDecision, HiperApp
from hiper.tui.tree_view import NotesEditor, TaskTree, TreePane
from tests.test_regressions import isolated, run_cli


def create_example() -> tuple[TaskNode, TaskNode, TaskNode]:
    trees.create_tree("Project", "10h")
    root = trees.load_forest().resolve("Project")
    trees.add_node(root.id, "Build", "5h")
    group = trees.load_forest().resolve("Project", "Build")
    trees.add_node(group.id, "Tests", "1h")
    leaf = trees.load_forest().resolve("Project", "Build/Tests")
    return root, group, leaf


def record(identifier: str, seconds: int, when: dt.datetime | None = None) -> None:
    target = trees.focus_target(identifier)
    start = when or dt.datetime.now()
    storage.save_session_csv(
        target.title,
        start,
        start + dt.timedelta(seconds=seconds),
        seconds,
        group=target.group,
        tree_id=target.tree_id,
        node_id=target.node_id,
    )


class TreeTests(TestCase):
    def test_subtree_totals_cutoff_and_title_isolation(self) -> None:
        with isolated():
            root, group, leaf = create_example()
            record(leaf.id, 600)
            record(group.id, 120)
            record(root.id, 30)
            record(leaf.id, 900, root.created_at - dt.timedelta(seconds=1))
            record(leaf.id, 10, root.created_at)
            trees.create_tree("Other")
            other = trees.load_forest().resolve("Other")
            trees.add_node(other.id, "Tests")
            other_leaf = trees.load_forest().resolve("Other", "Tests")
            record(other_leaf.id, 99)
            now = dt.datetime.now()
            storage.save_session_csv("Tests", now, now, 44)
            forest = trees.load_forest()
            totals = forest.totals(storage.load_sessions_csv())
            self.assertEqual(totals[leaf.id], 610)
            self.assertEqual(totals[group.id], 730)
            self.assertEqual(totals[root.id], 760)
            self.assertEqual(totals[other.id], 99)
            self.assertEqual(storage.load_goals_csv()[0]["time_worked_seconds"], 44)
            self.assertEqual(len(storage.load_goals_csv()), 1)
            sessions = storage.load_sessions_csv()
            self.assertEqual(sessions[0]["title"], "Tests")
            self.assertEqual(sessions[0]["group"], "Project/Build/Tests")
            self.assertEqual(sessions[1]["title"], "General")
            self.assertEqual(sessions[1]["group"], "Project/Build")
            storage.delete_record("session", sessions[0]["id"])
            self.assertEqual(forest.totals(storage.load_sessions_csv())[root.id], 160)

    def test_rename_add_child_and_delete_keep_identity(self) -> None:
        with isolated():
            root, group, leaf = create_example()
            record(leaf.id, 60)
            trees.update_node(leaf.id, name="Checks", estimate="2h")
            trees.add_node(leaf.id, "Unit")
            record(leaf.id, 20)
            forest = trees.load_forest()
            self.assertEqual(forest.resolve("Project", "Build/Checks").id, leaf.id)
            self.assertEqual(forest.totals(storage.load_sessions_csv())[root.id], 80)
            self.assertEqual(storage.load_sessions_csv()[1]["title"], "General")
            trees.delete_node(group.id)
            self.assertEqual(len(trees.load_forest().nodes), 1)
            self.assertEqual(len(storage.load_sessions_csv()), 2)
            trees.delete_node(root.id)
            trees.create_tree("Project")
            new = trees.load_forest()
            self.assertEqual(
                new.totals(storage.load_sessions_csv())[new.roots[0].id], 0
            )

    def test_validation_does_not_overwrite_valid_forest(self) -> None:
        with isolated():
            root, _, _ = create_example()
            path = Path(storage.get_data_dir()) / "trees.csv"
            before = path.read_bytes()
            for invalid in ("", "../bad", "a/b", "bad\nname"):
                with self.assertRaises(ValueError):
                    trees.add_node(root.id, invalid)
            with self.assertRaises(ValueError):
                trees.create_tree("Project")
            with self.assertRaises(ValueError):
                trees.add_node(root.id, "Build")
            with self.assertRaises(ValueError):
                trees.update_node(root.id, notes="file.txt")
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError):
                trees.TaskForest(
                    [root, replace(root, id="orphan", parent_id="missing")]
                )
            with self.assertRaises(ValueError):
                trees.TaskForest([root, replace(root, id="cycle", parent_id="cycle")])

    def test_legacy_sessions_remain_read_only_and_gain_optional_group_columns(
        self,
    ) -> None:
        with isolated() as directory:
            self.assertEqual(trees.load_forest().nodes, ())
            self.assertFalse((directory / "data").exists())
            path = directory / "data" / "sessions.csv"
            path.parent.mkdir()
            original = "title,start,end,duration,extra\nold,2026-01-01T10:00:00,2026-01-01T10:01:00,60,kept\n"
            path.write_text(original)
            old = storage.load_sessions_csv()[0]
            self.assertEqual(old["group"], "")
            self.assertEqual(old["tree_id"], "")
            self.assertEqual(path.read_text(), original)
            _, _, leaf = create_example()
            record(leaf.id, 30)
            with path.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["extra"], "kept")
            self.assertEqual(rows[0]["group"], "")
            self.assertEqual(rows[1]["group"], "Project/Build/Tests")
            self.assertEqual(storage.load_sessions_csv()[0]["id"], old["id"])

    def test_cli_create_add_show_set_log_delete(self) -> None:
        with isolated():
            for args in (
                ("tree", "create", "Study", "--estimate", "5h"),
                ("tree", "add", "Study", "--name", "Math"),
                (
                    "tree",
                    "add",
                    "Study",
                    "Math",
                    "--name",
                    "Proofs",
                    "--estimate",
                    "2h",
                ),
                ("tree", "set", "Study", "Math/Proofs", "--estimate", "3h"),
                (
                    "tree",
                    "log",
                    "Study",
                    "Math/Proofs",
                    "--duration",
                    "10m",
                    "--start",
                    (dt.datetime.now() + dt.timedelta(seconds=1)).isoformat(),
                ),
            ):
                code, _, error = run_cli(*args)
                self.assertEqual(code, 0, error)
            code, output, _ = run_cli("tree", "show", "Study")
            self.assertEqual(code, 0)
            self.assertIn("Study  10m00s", output)
            self.assertIn("Math  10m00s", output)
            self.assertIn("Proofs  10m00s", output)
            self.assertEqual(run_cli("tree", "delete", "Study", "Math")[0], 0)
            self.assertEqual(len(trees.load_forest().nodes), 1)
            self.assertEqual(len(storage.load_sessions_csv()), 1)
            self.assertEqual(
                run_cli("tree", "add", "Study", "missing", "--name", "x")[0], 1
            )

    def test_cli_focus_uses_same_metadata_as_tui_focus(self) -> None:
        with isolated():
            _, group, leaf = create_example()
            for identifier, path in ((group.id, "Build"), (leaf.id, "Build/Tests")):
                with mock.patch.object(fokus, "fokus_run", return_value=0) as run:
                    self.assertEqual(run_cli("tree", "focus", "Project", path)[0], 0)
                    self.assertEqual(
                        run.call_args.kwargs["tree_focus"],
                        trees.focus_target(identifier),
                    )
                session = services.create_tree_focus(identifier)
                self.assertEqual(session.node_id, identifier)
                self.assertEqual(session.group, trees.focus_target(identifier).group)
                session.save()
                self.assertEqual(storage.load_sessions_csv()[-1]["node_id"], identifier)

    def test_readable_notes_names_legacy_contents_and_rename(self) -> None:
        with isolated():
            root, _, leaf = create_example()
            self.assertEqual(trees.open_notes(root.id).path.name, "Project.md")
            document = trees.open_notes(leaf.id)
            self.assertEqual(document.path.name, "Project - Tests.md")
            legacy = document.path.parent / f"{leaf.id}.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("Legacy notes", encoding="utf-8")
            document = trees.open_notes(leaf.id)
            self.assertEqual(document.text, "Legacy notes")
            self.assertFalse(document.path.exists())
            trees.save_notes(document, document.text)
            self.assertEqual(document.path.read_text(), "Legacy notes")
            self.assertTrue(legacy.exists())
            trees.update_node(root.id, name="Renamed project")
            self.assertEqual(trees.open_notes(leaf.id).path, document.path)
            trees.update_node(leaf.id, name="Renamed node")
            self.assertEqual(trees.open_notes(leaf.id).text, "Legacy notes")

    def test_notes_managed_attached_conflicts_and_editor_argv(self) -> None:
        with isolated() as directory:
            root, _, leaf = create_example()
            document = trees.open_notes(leaf.id)
            self.assertFalse(document.path.exists())
            trees.save_notes(document, "# Testing\n\nDo it.\n")
            self.assertEqual(trees.open_notes(leaf.id).text, "# Testing\n\nDo it.\n")
            with self.assertRaisesRegex(ValueError, "changed on disk"):
                trees.save_notes(document, "stale")
            attached = directory / "notes with spaces.md"
            attached.write_text("existing", encoding="utf-8")
            trees.update_node(root.id, notes=str(attached))
            self.assertEqual(trees.open_notes(root.id).text, "existing")
            with (
                mock.patch.dict("os.environ", {"VISUAL": "my-editor --wait"}),
                mock.patch("hiper.trees.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                self.assertEqual(trees.edit_notes(root.id), 0)
                run.assert_called_once_with(
                    ["my-editor", "--wait", str(attached)], check=False
                )
            trees.delete_node(root.id)
            self.assertTrue(document.path.exists())
            self.assertEqual(attached.read_text(), "existing")


class TreeTuiTests(IsolatedAsyncioTestCase):
    async def test_click_leaf_and_group_focus_and_save_group_column(self) -> None:
        with isolated():
            root, group, leaf = create_example()
            app = HiperApp()
            async with app.run_test(size=(100, 45)) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                self.assertEqual(
                    app.query_one("#workspace", TabbedContent).active, "trees"
                )
                pane = app.query_one(TreePane)
                tree = app.query_one(TaskTree)
                tree.move_cursor(pane.node_widgets[leaf.id])
                await pilot.press("enter")
                await pilot.pause()
                self.assertIsNotNone(app.focus_session)
                assert app.focus_session is not None
                self.assertEqual(app.focus_session.group, "Project/Build/Tests")
                await pilot.press("ctrl+s")
                await pilot.pause()
                self.assertEqual(storage.load_sessions_csv()[0]["node_id"], leaf.id)
                await pilot.press("f2")
                await pilot.pause()
                # Mouse selection follows the same focus path for internal nodes.
                node = pane.node_widgets[group.id]
                tree.move_cursor(node)
                tree.scroll_to_node(node, animate=False)
                await pilot.pause()
                await pilot.click("#task-tree", offset=(16, node.line + 1))
                await pilot.pause()
                self.assertIsNone(app.focus_session)
                self.assertEqual(pane.selected_id, group.id)
                await pilot.click("#task-tree", offset=(16, node.line + 1), times=2)
                await pilot.pause()
                assert app.focus_session is not None
                self.assertEqual(app.focus_session.title, "General")
                self.assertEqual(app.focus_session.node_id, group.id)
                await pilot.press("ctrl+s")
                await pilot.pause()
                self.assertEqual(
                    storage.load_sessions_csv()[-1]["group"], "Project/Build"
                )
                self.assertEqual(len(trees.load_forest().nodes), 3)
                self.assertEqual(trees.load_forest().require(root.id).name, "Project")

    async def test_each_tree_has_a_tab_and_single_click_only_selects(self) -> None:
        with isolated():
            root, _, leaf = create_example()
            trees.create_tree("Other")
            other = trees.load_forest().resolve("Other")
            trees.add_node(other.id, "Tests")
            other_leaf = trees.load_forest().resolve("Other", "Tests")
            app = HiperApp()
            async with app.run_test(size=(100, 45)) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                pane = app.query_one(TreePane)
                tabs = app.query_one("#tree-tabs", Tabs)
                self.assertEqual(tabs.tab_count, 2)
                self.assertIn(leaf.id, pane.node_widgets)
                self.assertNotIn(other_leaf.id, pane.node_widgets)
                node = pane.node_widgets[leaf.id]
                await pilot.click("#task-tree", offset=(20, node.line + 1))
                await pilot.pause()
                self.assertIsNone(app.focus_session)
                self.assertEqual(pane.selected_id, leaf.id)
                await pilot.click(f"#tree-tab-{other.id}")
                await pilot.pause()
                self.assertEqual(pane.active_tree_id, other.id)
                self.assertNotIn(leaf.id, pane.node_widgets)
                self.assertIn(other_leaf.id, pane.node_widgets)
                node = pane.node_widgets[other_leaf.id]
                await pilot.click("#task-tree", offset=(16, node.line + 1))
                await pilot.pause()
                self.assertIsNone(app.focus_session)
                self.assertEqual(pane.selected_id, other_leaf.id)
                await pilot.press("ctrl+r")
                await pilot.pause()
                self.assertEqual(tabs.active, f"tree-tab-{other.id}")
                self.assertEqual(pane.selected_id, other_leaf.id)
                await pilot.click(f"#tree-tab-{root.id}")
                await pilot.pause()
                self.assertEqual(pane.selected_id, leaf.id)
                await pilot.click(f"#tree-tab-{other.id}")
                await pilot.pause()
                node = pane.node_widgets[other_leaf.id]
                await pilot.click("#task-tree", offset=(16, node.line + 1), times=2)
                await pilot.pause()
                assert app.focus_session is not None
                self.assertEqual(app.focus_session.node_id, other_leaf.id)

    async def test_create_add_edit_notes_and_confirm_delete(self) -> None:
        with isolated():
            app = HiperApp()
            async with app.run_test(size=(100, 50)) as pilot:
                await pilot.press("f2")
                await pilot.pause()
                app.query_one("#tree-name", Input).value = "Work"
                app.query_one("#tree-create", Button).press()
                await pilot.pause()
                root = trees.load_forest().resolve("Work")
                pane = app.query_one(TreePane)
                app.query_one(TaskTree).move_cursor(pane.node_widgets[root.id])
                await pilot.pause()
                app.query_one("#tree-child-name", Input).value = "Write"
                app.query_one("#tree-child-estimate", Input).value = "2h"
                app.query_one("#tree-add", Button).press()
                await pilot.pause()
                child = trees.load_forest().resolve("Work", "Write")
                self.assertEqual(child.estimate_seconds, 7200)
                app.query_one(TaskTree).move_cursor(pane.node_widgets[child.id])
                await pilot.pause()
                app.query_one("#tree-node-name", Input).value = "Draft"
                app.query_one("#tree-estimate", Input).value = "3h"
                app.query_one("#tree-update", Button).press()
                await pilot.pause()
                self.assertEqual(
                    trees.load_forest().require(child.id).estimate_seconds, 10800
                )
                app.query_one("#tree-notes", Button).press()
                await pilot.pause()
                self.assertIsInstance(app.screen, NotesEditor)
                app.screen.query_one(TextArea).load_text(
                    "# Draft\n\nNotes from the TUI."
                )
                await pilot.press("ctrl+r", "ctrl+enter")
                self.assertIsNone(app.focus_session)
                app.screen.query_one("#notes-save", Button).press()
                await pilot.pause()
                self.assertEqual(
                    trees.open_notes(child.id).text, "# Draft\n\nNotes from the TUI."
                )
                app.query_one("#tree-delete", Button).press()
                await pilot.pause()
                self.assertIsInstance(app.screen, DeleteDecision)
                await pilot.press("escape")
                await pilot.pause()
                self.assertEqual(len(trees.load_forest().nodes), 2)
                app.query_one("#tree-delete", Button).press()
                await pilot.pause()
                app.screen.query_one("#delete-confirm", Button).press()
                await pilot.pause()
                self.assertEqual(len(trees.load_forest().nodes), 1)


class TreeTerminalTests(TestCase):
    def test_cli_real_focus_keeps_group_when_saving(self) -> None:
        import os
        import termios

        from tests.test_terminal_integration import terminal_process, wait_for

        with isolated():
            _, group, _ = create_example()
            with terminal_process(command=("tree", "focus", "Project", "Build")) as (
                process,
                master,
                slave,
            ):
                wait_for(master, b":>")
                os.write(master, b" ")
                wait_for(master, b":> ")
                os.write(master, b"s\n")
                wait_for(master, b"Saved session:")
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertTrue(termios.tcgetattr(slave)[3] & termios.ICANON)
            session = storage.load_sessions_csv()[0]
            self.assertEqual(session["group"], "Project/Build")
            self.assertEqual(session["title"], "General")
            self.assertEqual(session["node_id"], group.id)
