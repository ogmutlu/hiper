import io
import os
import unittest
from contextlib import redirect_stdout
from typing import override
from unittest import mock

from hiper import rendering


class FokusRenderTest(unittest.TestCase):
    @override
    def tearDown(self) -> None:
        rendering._last_render_rows = 0

    def test_tick_render_moves_by_wrapped_screen_rows(self) -> None:
        terminal_size = os.terminal_size((10, 24))
        title = "abcdefghij"

        with (
            mock.patch("hiper.rendering.shutil.get_terminal_size") as size,
            mock.patch("hiper.rendering.config.get_config") as get_config,
            redirect_stdout(io.StringIO()) as output,
        ):
            size.return_value = terminal_size
            get_config.side_effect = lambda key, default: {
                "clock": "timer",
                "estimate_bar": "false",
                "countdown": "false",
                "today_time": "false",
            }.get(key, default)

            rendering._tick_render(
                0,
                session_title=title,
                is_first_render=True,
                context_time_before=0,
            )
            rendering._tick_render(
                1,
                session_title=title,
                context_time_before=0,
            )

        rendered = output.getvalue()

        self.assertIn("\033[5A\r", rendered)


if __name__ == "__main__":
    unittest.main()
