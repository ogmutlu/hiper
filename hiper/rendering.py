"""Focus display rendering; independent of input handling and session lifecycle."""

import shutil

from wcwidth import wcswidth

from . import config, storage
from .defaults import (
    DEFAULT_BAR_WIDTH,
    DEFAULT_CLOCK,
    DEFAULT_CLOCK_LENGTH,
    DEFAULT_COUNTDOWN,
    DEFAULT_ESTIMATE_BAR,
)


def _get_bar_width() -> int:
    # Get bar width from config (default: 42)
    try:
        bar_width = int(config.get_config("bar_width", DEFAULT_BAR_WIDTH))
        if bar_width <= 0:
            bar_width = int(DEFAULT_BAR_WIDTH)
    except (ValueError, TypeError):
        bar_width = int(DEFAULT_BAR_WIDTH)
    return bar_width


def _format_duration(seconds: int) -> str:
    return storage.format_hms(seconds)


_last_render_rows = 0


def _single_line(value: str) -> str:
    return "".join(
        character if ord(character) >= 32 and ord(character) != 127 else " "
        for character in value
    )


def _terminal_width() -> int:
    return max(1, shutil.get_terminal_size(fallback=(80, 24)).columns)


def _screen_rows_for_line(line: str, width: int) -> int:
    cells = max(0, wcswidth(line))
    return max(1, (cells + width - 1) // width)


def _screen_rows_for_lines(lines: list[str]) -> int:
    width = _terminal_width()
    return sum(_screen_rows_for_line(line, width) for line in lines)


def _clear_rendered_rows(row_count: int) -> None:
    for row_index in range(row_count):
        print("\033[2K", end="", flush=True)
        if row_index < row_count - 1:
            print("\033[1B\r", end="", flush=True)
    if row_count > 1:
        print(f"\033[{row_count - 1}A\r", end="", flush=True)


def _tick_render(
    elapsed_s: int,
    goal_override: str | None = None,
    session_title: str | None = None,
    is_first_render: bool = False,
    estimate_seconds: int | None = None,
    time_worked_before: int | None = None,
    context_time_before: int | None = None,
    today_time_before: int | None = None,
    online_status_line: str | None = None,
) -> None:
    session_title = _single_line(session_title) if session_title is not None else None
    online_status_line = (
        _single_line(online_status_line) if online_status_line else None
    )
    clock = config.get_config("clock", DEFAULT_CLOCK)
    if goal_override:
        clock = "bar"

    # Check if estimate bar is enabled
    estimate_bar_enabled = (
        config.get_config("estimate_bar", DEFAULT_ESTIMATE_BAR).lower() == "true"
    )
    countdown_enabled = (
        config.get_config("countdown", DEFAULT_COUNTDOWN).lower() == "true"
    )
    estimate_line = None

    # Render estimate bar if enabled and we have estimate data
    if (
        estimate_bar_enabled
        and estimate_seconds is not None
        and estimate_seconds > 0
        and time_worked_before is not None
    ):
        total_time_worked = time_worked_before + elapsed_s
        progress = total_time_worked / estimate_seconds if estimate_seconds > 0 else 1.0

        bar_width = _get_bar_width()

        # Create progress bar (capped at 100%)
        filled = min(int(progress * bar_width), bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        # Show percentage and time remaining/completed
        if total_time_worked >= estimate_seconds:
            # Estimate reached or exceeded
            estimate_line = (
                f":>{bar} {int(min(progress, 1.0) * 100)}% "
                f"(worked: {_format_duration(total_time_worked)})"
            )
        else:
            if countdown_enabled:
                remaining = estimate_seconds - total_time_worked
                estimate_line = (
                    f":>{bar} {int(progress * 100)}% "
                    f"(remaining: {_format_duration(remaining)})"
                )
            else:
                estimate_line = (
                    f":>{bar} {int(progress * 100)}% "
                    f"(estimate: {_format_duration(estimate_seconds)})"
                )

    # Render normal clock
    if clock == "dots":
        minutes = elapsed_s // 60
        dots = "." * minutes
        line = f":>{dots}" if dots else ":>"
    elif clock == "bar":
        # Parse target duration from goal override or clock_length config
        if goal_override:
            clock_length_str = goal_override
        else:
            clock_length_str = config.get_config("clock_length", DEFAULT_CLOCK_LENGTH)
        try:
            target_s = storage.parse_duration(clock_length_str)
        except (ValueError, TypeError) as e:
            # Fallback to 60 minutes if parsing fails
            print(f"Error: invalid clock length '{clock_length_str}': {e}")
            target_s = 3600

        # Calculate progress (can exceed 1.0 if target is exceeded)
        progress = elapsed_s / target_s if target_s > 0 else 1.0

        bar_width = _get_bar_width()

        # Create progress bar (capped at 100%)
        filled = min(int(progress * bar_width), bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        # Show percentage and time remaining/completed
        if elapsed_s >= target_s:
            # Target reached or exceeded
            line = (
                f":>{bar} {int(min(progress, 1.0) * 100)}% "
                f"(total: {_format_duration(elapsed_s)})"
            )
        else:
            if countdown_enabled:
                remaining = target_s - elapsed_s
                line = (
                    f":>{bar} {int(progress * 100)}% "
                    f"(remaining: {_format_duration(remaining)})"
                )
            else:
                line = f":>{bar} {int(progress * 100)}% (goal: {_format_duration(target_s)})"
    else:
        timer = _format_duration(elapsed_s)
        line = f":>{timer}"

    # Build context line if context_time_before is provided
    context_line = None
    if context_time_before is not None:
        total_context_time = context_time_before + elapsed_s
        context_line = f":>Total fokus towards {session_title}: {_format_duration(total_context_time)}"

    # Build today time line if today_time_before is provided
    today_line = None
    if today_time_before is not None:
        total_today_time = today_time_before + elapsed_s
        today_line = f":>Total fokus today: {_format_duration(total_today_time)}"

    # Count how many lines we need to render
    lines_to_render = [line]
    if estimate_line:
        lines_to_render.append(estimate_line)
    if context_line:
        lines_to_render.append(context_line)
    if today_line:
        lines_to_render.append(today_line)
    if online_status_line:
        lines_to_render.append(online_status_line)

    global _last_render_rows
    current_render_rows = _screen_rows_for_lines(lines_to_render)
    output = "\n".join(lines_to_render) + "\n"

    if is_first_render:
        print(output, end="", flush=True)
    else:
        # Lines can wrap, so move by the rendered screen rows from the last tick.
        previous_render_rows = _last_render_rows or current_render_rows
        print(f"\033[{previous_render_rows}A\r", end="", flush=True)
        _clear_rendered_rows(previous_render_rows)
        for render_line in lines_to_render:
            print(f"{render_line}\033[K\n", end="", flush=True)
    _last_render_rows = current_render_rows


def _finalize_render() -> None:
    """Finalize the current render line by printing a newline."""
    global _last_render_rows
    _last_render_rows = 0
    print()
