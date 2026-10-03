import datetime as dt
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase

from hiper import storage
from hiper.tui import services
from hiper.tui.app import DeleteDecision, HiperApp, RecordTable
from tests.test_regressions import isolated, run_cli


def seed() -> None:
    services.add_book("book", "100")
    services.add_habit("walk", "daily")
    services.save_goal("work", "1h", "")
    now = dt.datetime.now()
    storage.save_session_csv("work", now, now, 60)
    storage.append_log_csv("hello")


class DeleteTests(TestCase):
    def test_cli_deletes_all_record_types_and_preserves_history(self) -> None:
        with isolated():
            seed()
            for kind, key in (("book", "book"), ("habit", "walk"), ("goal", "work")):
                self.assertEqual(run_cli("delete", kind, "--key", key)[0], 0)
            self.assertEqual(storage.load_read_csv(), [])
            self.assertEqual(storage.load_habits_csv(), [])
            self.assertEqual(storage.load_goals_csv(), [])
            self.assertEqual(len(storage.load_sessions_csv()), 1)
            now = dt.datetime.now()
            storage.save_session_csv("another", now, now, 20)
            self.assertNotIn("work", [g["title"] for g in storage.load_goals_csv()])
            services.save_goal("work", "2h", "")
            self.assertIn("work", [g["title"] for g in storage.load_goals_csv()])
            for kind, records in (
                ("session", storage.load_sessions_csv()),
                ("log", storage.load_log_csv()),
            ):
                key = records[0]["id"]
                code, output, _ = run_cli("delete", kind, "--list")
                self.assertEqual(code, 0)
                self.assertIn(key, output)
                self.assertEqual(run_cli("delete", kind, "--key", key)[0], 0)
                self.assertEqual(run_cli("delete", kind, "--key", key)[0], 1)

    def test_legacy_duplicate_ids_survive_delete_and_append(self) -> None:
        with isolated() as root:
            path = root / "data" / "log.csv"
            path.parent.mkdir()
            original = "message,timestamp,custom\nhello,2026-10-02T10:00:00,keep\nhello,2026-10-02T10:00:00,keep\n"
            path.write_text(original)
            first, second = storage.load_log_csv()
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(path.read_text(), original)
            storage.delete_record("log", first["id"])
            self.assertEqual(storage.load_log_csv()[0]["id"], second["id"])
            with self.assertRaises(ValueError):
                storage.delete_record("log", first["id"])
            storage.append_log_csv("new")
            self.assertEqual(storage.load_log_csv()[0]["id"], second["id"])
            self.assertIn("keep", path.read_text())

    def test_missing_selection_does_not_rewrite_file(self) -> None:
        with isolated():
            seed()
            path = Path(storage.get_data_dir()) / "read.csv"
            before = path.read_bytes()
            self.assertEqual(run_cli("delete", "book", "--key", "missing")[0], 1)
            self.assertEqual(path.read_bytes(), before)


class TuiDeleteTests(IsolatedAsyncioTestCase):
    async def test_delete_each_type_with_cancel_and_confirmation(self) -> None:
        with isolated():
            seed()
            app = HiperApp()
            async with app.run_test(size=(100, 45)) as pilot:
                for kind, tab, table, load in (
                    ("book", "reading", "books", storage.load_read_csv),
                    ("goal", "goals", "goals", storage.load_goals_csv),
                    ("habit", "habits", "habits", storage.load_habits_csv),
                    ("session", "focus", "sessions", storage.load_sessions_csv),
                    ("log", "logs", "logs", storage.load_log_csv),
                ):
                    app.action_show_tab(tab)
                    await pilot.pause()
                    app.query_one(f"#{table}-table", RecordTable).focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    button = app.query_one(f"#{kind}-delete")
                    button.scroll_visible()
                    await pilot.pause()
                    await pilot.click(f"#{kind}-delete")
                    self.assertIsInstance(app.screen, DeleteDecision)
                    await pilot.press("ctrl+r", "ctrl+s", "f2", "escape")
                    await pilot.pause()
                    self.assertEqual(len(load()), 1)
                    await pilot.click(f"#{kind}-delete")
                    await pilot.click("#delete-confirm")
                    await pilot.pause()
                    self.assertEqual(load(), [])
