# hiper

A terminal companion for focus sessions, goals, reading, logs, and habits.
Requires Python 3.12+ and uv. Interactive focus mode and process locks use POSIX
terminal APIs (Linux/macOS).

## Run and develop

```sh
uv sync --locked
uv run hiper --help
uv run hiper --list
uv run hiper fokus --title "Write chapter"
uv run hiper postfokus --duration 25m --title "Write chapter"
uv run hiper prefokus --title "Write chapter" --estimate 4h --deadline 2026-12-01
uv run hiper read add --title "Book" --length 300
uv run hiper read update --title "Book" --plus 10 --time-per-page 45s
uv run hiper loop add --title "Walk" --freq mon,wed,fri
uv run hiper log "Walk"
```

The tracked `uv.lock` pins application and development dependencies. Both
`uv run hiper` and `uv run python -m hiper` propagate command exit codes.
`bin/hiper` runs the same locked project from any working directory.

To install the packaged application in a separate uv tool environment:

```sh
uv tool install .
# or: ./scripts/install.sh
```

The installer does not edit shell startup files. If uv's tool directory is absent
from PATH, use `uv tool update-shell`. Reinstall after changing a tool installation;
the repository launcher always runs the current checkout.

## Checks

```sh
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run python -m unittest discover -v
uv build
```

Ty treats every diagnostic as an error and checks application code and tests.
Ruff enforces annotations, modern Python syntax, import order, and bug checks.
Runtime records use explicit `TypedDict` schemas. The only explicit `Any` is at
the termios boundary, whose nested attributes are opaque operating-system values.

## Architecture

- `cli.py` builds argparse commands, dispatches them, handles expected errors,
  and opens short data transactions declared by each command.
- `commands/` coordinates workflows and presentation; command descriptors are
  immutable and require parser and execution callbacks.
- `models.py` defines session, goal, book, log, and habit records.
- `storage.py` validates and converts CSV records. Paths are resolved at runtime.
  Reads have no filesystem side effects. Worked time is derived from sessions
  in one pass, respecting the timestamp of the current estimate.
- `config.py` validates JSON string settings and commits complete setting updates.
  `defaults.py` is shared without depending on command modules.
- `files.py` writes complete snapshots through a temporary file and atomic replace.
  `locking.py` serializes cooperating processes and supports nested transactions.
- `session.py` tracks focus time with a monotonic clock, excluding pauses and
  retaining fractional seconds. `planning.py` contains the planning calculation.
- `terminal.py` owns POSIX input operations; `rendering.py` owns focus output and
  counts terminal cells for Unicode wrapping. `timeutil.py` shares parsing rules.

## Data and behaviour

Existing files remain in `~/.local/share/hiper`. `hiper set --savedir /absolute/path`
changes the data directory while configuration stays at its historical location.
`HIPER_CONFIG_FILE=/path/config.json` overrides the configuration path, useful
for isolated runs and tests. No user data is migrated automatically.

Existing CSVs with missing optional fields are supported. Appending sessions
preserves reordered headers and additional columns. Invalid JSON and malformed
CSV records fail explicitly; they are not silently discarded or replaced.
Snapshot writes are atomic, and cooperating hiper mutations take a process lock.
Manual editors and other programs do not participate in that locking protocol.
A saved session remains saved if refreshing the derived goals snapshot fails;
the command prints a warning and future reads derive totals again.

ISO timestamps with offsets are converted to local wall time to interoperate
with existing naive timestamps. Session statistics attribute a session to its
start date. Explicit past-session start/end times describe the wall-clock span;
its supplied duration can exclude breaks. Bare duration numbers mean minutes.

In focus mode, press Space to pause. While paused, use Enter to resume, `s` to
save, `d` to discard, or `help` for more commands. Focus mode requires interactive
input and output. Reading progress displays without prompting when stdin is
redirected. Interruptions exit with status 130; ordinary errors return nonzero.

`--online` shares status through files in the configured data directory. A paused
user is not reported as active. Status cleanup runs on handled exits; a hard kill
or machine crash can leave an old status file. Pause-end MP3 playback optionally
uses VLC when configured.

## Interactive TUI

```sh
uv run hiper tui
uv run hiper tui --title "Write chapter"
```

The Textual interface shares the CLI's configuration and CSV files. It offers
Focus, Goals, Reading, Habits, and Logs tabs, plus today's focus total and recent
sessions. Select table rows with Enter or a mouse click before using their actions.
Forms validate input and show errors in the status bar. File operations run in
background threads so the timer and keyboard remain responsive.

- F1–F5 switch tabs; Tab / Shift+Tab move between controls.
- Ctrl+Enter starts focus; Ctrl+P pauses or resumes; Ctrl+S saves the session.
- Ctrl+R refreshes data written by other hiper processes.
- Ctrl+Q quits. With an unsaved session, choose Save & quit, Discard & quit, or
  Keep working. A failed save retains the paused session so you can retry.

Focus title, comment, and target are fixed while a session is active. You can
continue managing goals, books, habits, and logs during a session. The Discard
button ends the active session without writing it. Goal estimates can be created
or revised, goals can be finished, selected books can launch a reading session,
and completing a habit appends an idempotent completion entry for today.

The TUI uses `hiper/tui/app.py` and `app.tcss` for presentation;
`hiper/tui/services.py` contains typed workflows. It reuses `SessionClock`, atomic
CSV writes, process locks, and shared habit rules. Headless interaction tests
exercise the actual widgets, keyboard shortcuts, validation, saves, and quit
screens alongside the existing CLI and pseudo-terminal tests. The CLI's `--online`
status sharing and VLC pause alarms remain available through their CLI commands.

Delete records with `uv run hiper delete KIND --key KEY`, where KIND is
`book`, `goal`, `session`, `habit`, or `log`. Books and goals use their exact
title; habits use their exact name. Use `uv run hiper delete session --list`
or `uv run hiper delete log --list` to obtain stable record IDs. `--list`
also works for the other kinds and does not modify data.

In the TUI, select a table row with Enter, press its **Delete** button, and
confirm the dialog. Escape cancels. Deletion preserves other records, including
session history associated with deleted goals and logs associated with habits.
Deleted goals stay removed until you explicitly create them again. Session/log
IDs are added to older CSVs on their next mutation; reading alone never rewrites
files. Deletion cannot be undone.
