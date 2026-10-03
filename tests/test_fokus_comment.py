import csv
import datetime as dt
import os
import tempfile
import unittest
from unittest import mock

from hiper import storage
from hiper.commands import fokus


class FokusCommentTest(unittest.TestCase):
    def test_save_session_writes_comment_column(self) -> None:
        start = dt.datetime(2026, 6, 8, 9, 0, 0)
        end = dt.datetime(2026, 6, 8, 9, 5, 0)

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("hiper.storage.config.get_data_dir", return_value=tmp):
                path = storage.save_session_csv(
                    "something", start, end, 300, comment="comment"
                )

            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual(rows[0]["title"], "something")
        self.assertEqual(rows[0]["comment"], "comment")

    def test_save_session_adds_comment_column_to_existing_csv(self) -> None:
        start = dt.datetime(2026, 6, 8, 9, 0, 0)
        end = dt.datetime(2026, 6, 8, 9, 5, 0)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sessions.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["title", "start", "end", "duration", "duration_formatted"]
                )
                writer.writerow(
                    [
                        "old",
                        start.isoformat(),
                        end.isoformat(),
                        "300",
                        "05m00s",
                    ]
                )

            with mock.patch("hiper.storage.config.get_data_dir", return_value=tmp):
                storage.save_session_csv("new", start, end, 300, comment="fresh")

            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual(rows[0]["comment"], "")
        self.assertEqual(rows[1]["comment"], "fresh")

    def test_online_fokus_line_includes_comment(self) -> None:
        self.assertEqual(
            fokus._online_fokus_line("something", "comment"),
            "fokus: something :: comment",
        )

    def test_online_status_prints_comment_as_phrase(self) -> None:
        self.assertEqual(
            fokus._format_online_status_line("nick", "something :: comment", True),
            ":>nick is fokusing on something with comment comment right now",
        )


if __name__ == "__main__":
    unittest.main()
