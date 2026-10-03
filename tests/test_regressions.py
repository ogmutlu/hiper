import csv
import datetime as dt
import io
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from hiper import config, rendering, storage
from hiper.cli import build_parser, main
from hiper.commands import fokus, log, prefokus
from hiper.files import atomic_text_writer
from hiper.models import Goal, Habit
from hiper.session import SessionClock


@contextmanager
def isolated() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with mock.patch.dict(
            os.environ, {"HIPER_CONFIG_FILE": str(root / "config.json")}
        ):
            config.set_config("savedir", str(root / "data"))
            yield root


def run_cli(*args: str) -> tuple[int, str, str]:
    with (
        redirect_stdout(io.StringIO()) as stdout,
        redirect_stderr(io.StringIO()) as stderr,
    ):
        code = main(list(args))
    return code, stdout.getvalue(), stderr.getvalue()


class PersistenceTests(unittest.TestCase):
    def test_reads_do_not_create_files(self) -> None:
        with isolated() as root:
            self.assertEqual(storage.load_sessions_csv(), [])
            self.assertEqual(storage.load_goals_csv(), [])
            self.assertEqual(storage.load_read_csv(), [])
            self.assertEqual(storage.load_habits_csv(), [])
            self.assertEqual(storage.load_log_csv(), [])
            self.assertIsNone(storage.get_other_online_fokus_status("me"))
            self.assertFalse((root / "data").exists())

    def test_atomic_failure_preserves_existing_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text("original")
            with self.assertRaises(ValueError), atomic_text_writer(path) as stream:
                stream.write("partial")
                raise ValueError("serialization failed")
            self.assertEqual(path.read_text(), "original")
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_corrupt_config_is_not_overwritten(self) -> None:
        with isolated() as root:
            path = root / "config.json"
            path.write_text('["not a config"]')
            code, _, error = run_cli("set", "--nick", "new")
            self.assertEqual(code, 1)
            self.assertIn("configuration must be an object", error)
            self.assertEqual(path.read_text(), '["not a config"]')

    def test_invalid_settings_do_not_partially_commit(self) -> None:
        with isolated():
            config.set_config("nick", "old")
            code, _, _ = run_cli("set", "--nick", "new", "--clock", "bar=bad")
            self.assertEqual(code, 1)
            self.assertEqual(config.get_config("nick"), "old")
            self.assertEqual(config.get_config("clock"), "")

    def test_savedir_change_is_immediately_visible(self) -> None:
        with isolated() as root:
            new_dir = root / "new"
            self.assertEqual(run_cli("set", "--savedir", str(new_dir))[0], 0)
            self.assertEqual(run_cli("log", "hello")[0], 0)
            self.assertTrue((new_dir / "log.csv").exists())
            self.assertFalse((root / "data" / "log.csv").exists())

    def test_append_preserves_reordered_and_extra_columns(self) -> None:
        with isolated() as root:
            data = root / "data"
            data.mkdir()
            path = data / "sessions.csv"
            path.write_text(
                "duration,title,end,start,custom\n60,old,2026-01-01T10:01:00,2026-01-01T10:00:00,keep\n"
            )
            start = dt.datetime(2026, 1, 1, 11)
            storage.save_session_csv(
                "new", start, start + dt.timedelta(seconds=30), 30, "note"
            )
            with path.open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["custom"], "keep")
            self.assertEqual(rows[1]["title"], "new")
            self.assertEqual(rows[1]["comment"], "note")
            self.assertEqual(len(storage.load_sessions_csv()), 2)

    def test_malformed_csv_fails_without_replacing_data(self) -> None:
        with isolated() as root:
            data = root / "data"
            data.mkdir()
            path = data / "read.csv"
            contents = "title,length,current_page\nbroken,100\n"
            path.write_text(contents)
            code, _, error = run_cli("read", "update", "--title", "broken", "--at", "1")
            self.assertEqual(code, 1)
            self.assertIn("malformed CSV row", error)
            self.assertEqual(path.read_text(), contents)

    def test_sessions_reject_negative_duration_and_reversed_times(self) -> None:
        with isolated():
            start = dt.datetime(2026, 1, 1)
            for end, duration in ((start, -1), (start - dt.timedelta(seconds=1), 0)):
                with self.subTest(duration=duration), self.assertRaises(ValueError):
                    storage.save_session_csv("x", start, end, duration)

    def test_offsets_are_normalized_for_statistics(self) -> None:
        with isolated():
            self.assertEqual(
                run_cli(
                    "postfokus",
                    "--duration",
                    "1m",
                    "--start",
                    "2026-01-01T10:00:00+00:00",
                )[0],
                0,
            )
            self.assertEqual(run_cli("postfokus")[0], 0)
            self.assertIsNone(storage.load_sessions_csv()[0]["start"].tzinfo)

    def test_parallel_log_writers_preserve_all_entries(self) -> None:
        with isolated():
            processes = [
                subprocess.Popen(
                    [sys.executable, "-m", "hiper", "log", str(i)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for i in range(8)
            ]
            for process in processes:
                _, error = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, error.decode())
            self.assertEqual(
                {row["message"] for row in storage.load_log_csv()},
                {str(i) for i in range(8)},
            )


class CommandTests(unittest.TestCase):
    def test_module_propagates_exit_status(self) -> None:
        with isolated():
            result = subprocess.run(
                [sys.executable, "-m", "hiper", "set", "--bar-width", "0"],
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)

    def test_help_does_not_read_broken_config(self) -> None:
        with isolated() as root:
            (root / "config.json").write_text("invalid JSON")
            result = subprocess.run(
                [sys.executable, "-m", "hiper", "--help"],
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn(b"postfokus", result.stdout)

    def test_every_registered_command_has_help(self) -> None:
        parser = build_parser()
        self.assertIn("fokus", parser.format_help())
        from hiper.commands import COMMAND_REGISTRY

        for name in COMMAND_REGISTRY:
            with (
                self.subTest(command=name),
                redirect_stdout(io.StringIO()),
                self.assertRaises(SystemExit) as exit_info,
            ):
                main([name, "--help"])
            self.assertEqual(exit_info.exception.code, 0)

    def test_book_progress_and_timing_can_be_updated_together(self) -> None:
        with isolated():
            self.assertEqual(
                run_cli("read", "add", "--title", "book", "--length", "100")[0], 0
            )
            self.assertEqual(
                run_cli(
                    "read",
                    "update",
                    "--title",
                    "book",
                    "--plus",
                    "10",
                    "--time-per-page",
                    "45s",
                )[0],
                0,
            )
            book = storage.load_read_csv()[0]
            self.assertEqual(book["current_page"], 10)
            self.assertEqual(book["time_per_page_seconds"], 45)
            self.assertEqual(
                run_cli("read", "update", "--title", "book", "--at", "101")[0], 1
            )
            self.assertEqual(storage.load_read_csv()[0]["current_page"], 10)

    def test_blank_book_title_fails(self) -> None:
        with isolated():
            self.assertEqual(
                run_cli("read", "add", "--title", " ", "--length", "10")[0], 1
            )

    def test_missing_book_returns_error(self) -> None:
        with isolated():
            self.assertEqual(run_cli("read", "--title", "missing")[0], 1)

    def test_invalid_habit_frequency_is_rejected(self) -> None:
        with isolated():
            self.assertEqual(
                run_cli("loop", "add", "--title", "habit", "--freq", "mon,typo")[0], 1
            )
            self.assertEqual(storage.load_habits_csv(), [])

    def test_habit_statistics_count_only_scheduled_days_after_creation(self) -> None:
        with isolated():
            # 28 Sep 2026 is Monday; the Tuesday completion must not raise the rate.
            created = dt.datetime(2026, 9, 28)
            storage.save_habits_csv(
                [Habit(name="habit", frequency="mon", created_at=created)]
            )
            storage.append_log_csv("habit", created)
            storage.append_log_csv("habit", created + dt.timedelta(days=1))
            code, output, _ = run_cli(
                "loop", "statistics", "--since", "2026-09-01", "--until", "2026-09-30"
            )
            self.assertEqual(code, 0)
            self.assertIn("habit: 1/1 (100.0%)", output)

    def test_date_only_log_until_includes_entire_day(self) -> None:
        until = log._parse_datetime("2026-01-01", is_until=True)
        self.assertEqual(until.time(), dt.time.max)
        with isolated():
            storage.append_log_csv("evening", dt.datetime(2026, 1, 1, 23, 30))
            self.assertIn("evening", run_cli("log", "--until", "2026-01-01")[1])

    def test_log_write_and_filters_cannot_silently_discard_message(self) -> None:
        with isolated():
            self.assertEqual(run_cli("log", "message", "--all")[0], 1)
            self.assertEqual(storage.load_log_csv(), [])

    def test_goal_accounting_respects_new_estimate_timestamp(self) -> None:
        with isolated():
            old = dt.datetime(2026, 1, 1, 10)
            new = old + dt.timedelta(days=1)
            storage.save_session_csv("goal", old, old + dt.timedelta(hours=1), 3600)
            storage.save_session_csv("goal", new, new + dt.timedelta(minutes=5), 300)
            goal = Goal(
                title="goal",
                estimate_seconds=600,
                estimate_formatted="10m00s",
                estimate_timestamp=new,
                deadline=None,
                time_worked_seconds=0,
                time_worked_formatted="",
                start_by=None,
            )
            storage.save_goals_csv([goal])
            updated = prefokus._update_time_worked(storage.load_goals_csv())[0]
            self.assertEqual(updated["time_worked_seconds"], 300)
            self.assertEqual(updated["time_worked_formatted"], "05m00s")
            self.assertEqual(run_cli("prefokus", "--title", "goal")[0], 0)

    def test_finished_goals_are_hidden_from_current_estimates(self) -> None:
        with isolated():
            self.assertEqual(
                run_cli("prefokus", "--title", "goal", "--estimate", "1h")[0], 0
            )
            self.assertEqual(run_cli("finish", "--title", "goal")[0], 0)
            self.assertIn(
                "No goals found with current estimates", run_cli("prefokus")[1]
            )
            self.assertIn("goal", run_cli("prefokus", "--all")[1])

    def test_invalid_time_and_reversed_date_range_fail(self) -> None:
        with isolated():
            self.assertNotEqual(
                run_cli("postfokus", "--duration", "1m", "--start", "10:00:bad")[0], 0
            )
            self.assertNotEqual(
                run_cli("postfokus", "--since", "2026-02-01", "--until", "2026-01-01")[
                    0
                ],
                0,
            )


class TerminalTests(unittest.TestCase):
    def test_malformed_save_command_does_not_save(self) -> None:
        for command in (
            "savejunk",
            "save --title",
            'save --title "unclosed',
            "save --unknown",
        ):
            with self.subTest(command=command):
                self.assertEqual(fokus._parse_save_command(command), (False, None))
        self.assertEqual(
            fokus._parse_save_command('save --title "new title"'), (True, "new title")
        )

    def test_goal_command_requires_exact_name_and_positive_duration(self) -> None:
        self.assertEqual(fokus._parse_goal_command("goaljunk 1h"), (False, None, None))
        self.assertIsNotNone(fokus._parse_goal_command("goal 0s")[2])

    def test_online_comment_without_title_stays_a_comment(self) -> None:
        line = fokus._online_fokus_line(None, "note")
        status = line.removeprefix("fokus:").strip()
        self.assertEqual(
            fokus._format_online_status_line("nick", status, True),
            ":>nick is fokusing with comment note right now",
        )

    def test_clock_preserves_fractional_seconds_and_excludes_pauses(self) -> None:
        with mock.patch("time.monotonic") as now:
            now.return_value = 0.0
            clock = SessionClock(now=now)
            now.return_value = 0.6
            clock.pause()
            now.return_value = 100.0
            self.assertEqual(clock.seconds, 0)
            clock.resume()
            now.return_value = 100.6
            clock.pause()
            self.assertEqual(clock.seconds, 1)

    def test_unicode_width_counts_terminal_cells(self) -> None:
        self.assertEqual(rendering._screen_rows_for_line("界界界", 4), 2)
        self.assertEqual(rendering._screen_rows_for_line("e\u0301e\u0301", 2), 1)

    def test_fokus_rejects_noninteractive_input(self) -> None:
        with isolated(), mock.patch("sys.stdin.isatty", return_value=False):
            self.assertEqual(run_cli("fokus")[0], 1)

    def test_first_render_failure_restores_terminal_and_online_status(self) -> None:
        with (
            isolated(),
            redirect_stdout(io.StringIO()),
            mock.patch("sys.stdin.isatty", return_value=True),
            mock.patch("sys.stdout.isatty", return_value=True),
        ):
            config.set_config("nick", "me")
            args = build_parser().parse_args(["fokus", "--online"])
            with (
                mock.patch.object(fokus, "_set_raw_mode", return_value=(42, [])),
                mock.patch.object(fokus, "_restore_mode") as restore,
                mock.patch.object(
                    fokus, "_tick_render", side_effect=ValueError("failed render")
                ),
                self.assertRaises(ValueError),
            ):
                fokus.fokus_run(args)
            restore.assert_called_once_with(42, [])
            path = Path(storage.get_online_dir()) / "me.txt"
            self.assertEqual(path.read_text().splitlines()[-1], "end")

    def test_paused_online_user_is_not_reported_as_active(self) -> None:
        with isolated():
            storage.append_online_fokus_line("other", "fokus: task")
            storage.append_online_fokus_line("other", "pause")
            self.assertEqual(
                storage.get_other_online_fokus_status("me"), ("other", "task", False)
            )


if __name__ == "__main__":
    unittest.main()
