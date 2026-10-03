import datetime as dt
from unittest import IsolatedAsyncioTestCase, TestCase, mock

from textual.widgets import Button, Input, TabbedContent

from hiper import storage
from hiper.tui import services
from hiper.tui.app import HiperApp, RecordTable, SessionDecision
from tests.test_regressions import isolated, run_cli


class TuiServiceTests(TestCase):
    def test_goal_and_book_mutations_share_cli_data(self) -> None:
        with isolated():
            services.save_goal("project", "2h", "2026-12-01")
            self.assertEqual(storage.load_goals_csv()[0]["estimate_seconds"], 7200)
            services.finish_goal("project")
            self.assertEqual(storage.load_goals_csv()[0]["estimate_seconds"], 0)
            services.add_book("book", "100")
            services.update_book("book", "15", "45s")
            self.assertEqual(storage.load_read_csv()[0]["current_page"], 15)
            self.assertEqual(storage.load_read_csv()[0]["time_per_page_seconds"], 45)
            with self.assertRaises(ValueError):
                services.update_book("book", "101", "60s")
            self.assertEqual(storage.load_read_csv()[0]["current_page"], 15)

    def test_habit_completion_is_idempotent(self) -> None:
        with isolated():
            services.add_habit("walk", "daily")
            services.complete_habit("walk")
            services.complete_habit("walk")
            self.assertEqual(len(storage.load_log_csv()), 1)
            self.assertTrue(services.habit_done_today("walk", storage.load_log_csv()))

    def test_invalid_goal_does_not_replace_previous_estimate(self) -> None:
        with isolated():
            services.save_goal("project", "2h", "")
            with self.assertRaises(ValueError):
                services.save_goal("project", "3h", "bad date")
            self.assertEqual(storage.load_goals_csv()[0]["estimate_seconds"], 7200)

    def test_tui_command_requires_terminal(self) -> None:
        with isolated(), mock.patch("sys.stdin.isatty", return_value=False):
            code, _, error = run_cli("tui")
            self.assertEqual(code, 1)
            self.assertIn("interactive terminal", error)


class TuiInteractionTests(IsolatedAsyncioTestCase):
    async def test_mount_reads_without_creating_data_and_tabs_are_keyboard_accessible(
        self,
    ) -> None:
        with isolated() as root:
            app = HiperApp()
            async with app.run_test(size=(80, 24)) as pilot:
                self.assertIsNotNone(app.snapshot)
                self.assertFalse((root / "data").exists())
                await pilot.press("f3")
                self.assertEqual(app.query_one(TabbedContent).active, "reading")
                await pilot.press("f5")
                self.assertEqual(app.query_one(TabbedContent).active, "logs")

    async def test_start_pause_resume_and_save_focus(self) -> None:
        with isolated():
            app = HiperApp(focus_title="task")
            async with app.run_test(size=(100, 40)) as pilot:
                app.query_one("#focus-comment", Input).value = "context"
                app.query_one("#focus-target", Input).value = "25m"
                await pilot.press("ctrl+enter")
                session = app.focus_session
                self.assertIsNotNone(session)
                self.assertTrue(app.query_one("#focus-title", Input).disabled)
                await pilot.press("ctrl+p")
                assert session is not None
                self.assertTrue(session.paused)
                await pilot.press("ctrl+p")
                self.assertFalse(session.paused)
                await pilot.press("ctrl+s")
                self.assertIsNone(app.focus_session)
                self.assertFalse(app.query_one("#focus-title", Input).disabled)
                sessions = storage.load_sessions_csv()
                self.assertEqual(sessions[0]["title"], "task")
                self.assertEqual(sessions[0]["comment"], "context")
                self.assertEqual(
                    app.query_one("#sessions-table", RecordTable).row_count, 1
                )

    async def test_failed_save_keeps_session_for_retry(self) -> None:
        with isolated():
            app = HiperApp(focus_title="task")
            async with app.run_test() as pilot:
                await pilot.press("ctrl+enter")
                session = app.focus_session
                with mock.patch(
                    "hiper.tui.services.storage.save_session_csv",
                    side_effect=OSError("disk unavailable"),
                ):
                    await pilot.press("ctrl+s")
                self.assertIs(app.focus_session, session)
                assert session is not None
                self.assertTrue(session.paused)
                self.assertEqual(storage.load_sessions_csv(), [])
                await pilot.press("ctrl+s")
                self.assertIsNone(app.focus_session)
                self.assertEqual(len(storage.load_sessions_csv()), 1)

    async def test_log_input_submits_and_rich_markup_is_literal(self) -> None:
        with isolated():
            app = HiperApp()
            async with app.run_test() as pilot:
                await pilot.press("f5")
                message = app.query_one("#log-message", Input)
                message.value = "[red]a note[/red]"
                message.focus()
                await pilot.press("enter")
                self.assertEqual(
                    storage.load_log_csv()[0]["message"], "[red]a note[/red]"
                )
                self.assertEqual(message.value, "")
                table = app.query_one("#logs-table", RecordTable)
                self.assertEqual(table.get_row_at(0)[1].plain, "[red]a note[/red]")

    async def test_select_book_update_and_prepare_reading_session(self) -> None:
        with isolated():
            services.add_book("book", "100")
            app = HiperApp()
            async with app.run_test(size=(100, 45)) as pilot:
                await pilot.press("f3")
                app.query_one("#books-table", RecordTable).focus()
                await pilot.press("enter")
                self.assertEqual(app.selected_book, "book")
                app.query_one("#book-page", Input).value = "10"
                app.query_one("#book-time", Input).value = "30s"
                await pilot.click("#book-update")
                self.assertEqual(storage.load_read_csv()[0]["current_page"], 10)
                await pilot.click("#book-focus")
                self.assertEqual(app.query_one(TabbedContent).active, "focus")
                self.assertEqual(app.query_one("#focus-title", Input).value, "book")

    async def test_quit_can_cancel_or_save_an_unsaved_session(self) -> None:
        with isolated():
            app = HiperApp(focus_title="task")
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.press("ctrl+enter", "ctrl+q")
                self.assertIsInstance(app.screen, SessionDecision)
                await pilot.press("escape")
                self.assertNotIsInstance(app.screen, SessionDecision)
                self.assertIsNotNone(app.focus_session)
                await pilot.press("ctrl+q")
                await pilot.click("#decision-save")
                self.assertEqual(len(storage.load_sessions_csv()), 1)
                self.assertIsNone(app.focus_session)

    async def test_quit_discard_does_not_save(self) -> None:
        with isolated():
            app = HiperApp()
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.press("ctrl+enter", "ctrl+q")
                await pilot.click("#decision-discard")
                self.assertEqual(storage.load_sessions_csv(), [])

    async def test_refresh_failure_after_save_does_not_duplicate_session(self) -> None:
        with isolated():
            app = HiperApp()
            async with app.run_test() as pilot:
                await pilot.press("ctrl+enter")
                with mock.patch(
                    "hiper.tui.services.load_snapshot",
                    side_effect=ValueError("broken books"),
                ):
                    await pilot.press("ctrl+s")
                self.assertIsNone(app.focus_session)
                self.assertEqual(len(storage.load_sessions_csv()), 1)
                await pilot.press("ctrl+s")
                self.assertEqual(len(storage.load_sessions_csv()), 1)

    async def test_goal_form_create_select_and_finish(self) -> None:
        with isolated():
            app = HiperApp()
            async with app.run_test(size=(100, 45)) as pilot:
                await pilot.press("f2")
                app.query_one("#goal-title", Input).value = "project"
                app.query_one("#goal-estimate", Input).value = "4h"
                app.query_one("#goal-deadline", Input).value = "2026-12-01"
                await pilot.click("#goal-save")
                self.assertEqual(storage.load_goals_csv()[0]["estimate_seconds"], 14400)
                app.query_one("#goals-table", RecordTable).focus()
                await pilot.press("enter")
                self.assertEqual(app.selected_goal, "project")
                await pilot.click("#goal-finish")
                self.assertEqual(storage.load_goals_csv()[0]["estimate_seconds"], 0)

    async def test_habit_form_and_completion(self) -> None:
        with isolated():
            app = HiperApp()
            async with app.run_test(size=(100, 45)) as pilot:
                await pilot.press("f4")
                app.query_one("#habit-title", Input).value = "walk"
                await pilot.click("#habit-add")
                app.query_one("#habits-table", RecordTable).focus()
                await pilot.press("enter")
                await pilot.click("#habit-complete")
                await pilot.click("#habit-complete")
                self.assertEqual(len(storage.load_log_csv()), 1)
                self.assertEqual(
                    app.query_one("#habits-table", RecordTable).get_row_at(0)[2].plain,
                    "Done",
                )

    async def test_modal_blocks_background_actions_and_duplicate_quit(self) -> None:
        with isolated():
            app = HiperApp()
            async with app.run_test(size=(60, 24)) as pilot:
                await pilot.press("ctrl+enter", "ctrl+q")
                decision = app.screen
                await pilot.press("ctrl+p", "ctrl+s", "ctrl+r", "f3", "ctrl+q")
                self.assertIs(app.screen, decision)
                self.assertIsNotNone(app.focus_session)
                self.assertEqual(storage.load_sessions_csv(), [])
                await pilot.press("escape")
                self.assertNotIsInstance(app.screen, SessionDecision)

    async def test_existing_cli_data_is_visible_on_mount(self) -> None:
        with isolated():
            start = dt.datetime.now()
            storage.save_session_csv("previous", start, start, 120)
            app = HiperApp()
            async with app.run_test():
                self.assertEqual(
                    app.query_one("#sessions-table", RecordTable).row_count, 1
                )
                self.assertIsNotNone(app.snapshot)

    async def test_empty_forms_show_errors_without_crashing(self) -> None:
        with isolated():
            app = HiperApp()
            async with app.run_test() as pilot:
                await pilot.press("f5")
                await pilot.click("#log-add")
                self.assertEqual(storage.load_log_csv(), [])
                self.assertFalse(app.busy)
                self.assertFalse(app.query_one("#log-add", Button).disabled)
