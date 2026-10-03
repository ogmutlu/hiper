"""Textual widgets and event orchestration for hiper."""

import asyncio
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import ClassVar, override

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Static,
    TabbedContent,
    TabPane,
)

from .. import storage
from ..habits import is_scheduled_today
from ..timeutil import format_hms
from . import services
from .services import FocusSession, Snapshot


class RecordTable(DataTable[Text]):
    def __init__(self, identifier: str) -> None:
        super().__init__(id=identifier, cursor_type="row", zebra_stripes=True)


class SessionDecision(ModalScreen[str]):
    """Keep an unsaved focus session from being accidentally lost."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Keep working")
    ]

    @override
    def compose(self) -> ComposeResult:
        with Vertical(id="decision"):
            yield Static("You have an unsaved focus session", classes="section-title")
            yield Static("Save it, discard it, or keep working.", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Save & quit", id="decision-save", variant="primary")
                yield Button("Discard & quit", id="decision-discard", variant="error")
                yield Button("Keep working", id="decision-stay")

    def action_cancel(self) -> None:
        self.dismiss("stay")

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        self.dismiss((event.button.id or "decision-stay").removeprefix("decision-"))


class DeleteDecision(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, description: str) -> None:
        super().__init__()
        self.description = description

    @override
    def compose(self) -> ComposeResult:
        with Vertical(id="decision"):
            yield Static(f"Delete {self.description}?", markup=False)
            yield Static("This cannot be undone. Other records are kept.", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="delete-cancel", variant="primary")
                yield Button("Delete", id="delete-confirm", variant="error")

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "delete-confirm")


class HiperApp(App[None]):
    TITLE = "hiper"
    SUB_TITLE = "make room for focused work"
    CSS_PATH = "app.tcss"
    COMMAND_PALETTE_BINDING = "ctrl+k"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+enter", "start_focus", "Start focus", priority=True),
        Binding("ctrl+p", "pause_focus", "Pause / resume", priority=True),
        Binding("ctrl+s", "save_focus", "Save session", priority=True),
        Binding("ctrl+r", "reload_data", "Refresh", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        *[
            Binding(f"f{number}", f"show_tab('{tab}')", show=False, priority=True)
            for number, tab in enumerate(
                ("focus", "goals", "reading", "habits", "logs"), 1
            )
        ],
    ]

    def __init__(self, *, focus_title: str = "") -> None:
        super().__init__()
        self._io_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="hiper-io"
        )
        self.initial_focus_title = focus_title
        self.focus_session: FocusSession | None = None
        self.snapshot: Snapshot | None = None
        self.selected_session: str | None = None
        self.selected_log: str | None = None
        self.selected_goal: str | None = None
        self.selected_book: str | None = None
        self.selected_habit: str | None = None
        self.busy = False
        self._last_focus_render: tuple[int, bool, str, str, int | None] | None = None

    @override
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Loading your workspace…", id="summary", markup=False)
        with TabbedContent(initial="focus", id="workspace"):
            with TabPane("Focus  F1", id="focus"):
                with VerticalScroll():
                    with Vertical(classes="card"):
                        yield Static("ONE THING AT A TIME", classes="eyebrow")
                        yield Static(
                            "Ready when you are", id="session-state", markup=False
                        )
                        yield Static("00m00s", id="timer", markup=False)
                        yield Static(
                            "Start a session below. Pauses do not count toward focus time.",
                            id="session-detail",
                            markup=False,
                        )
                    yield Static("What are you working on?", classes="field-label")
                    yield Input(
                        value=self.initial_focus_title,
                        placeholder="Session title (optional)",
                        id="focus-title",
                    )
                    yield Static("A little context", classes="field-label")
                    yield Input(placeholder="Comment (optional)", id="focus-comment")
                    yield Static("Time target", classes="field-label")
                    yield Input(
                        placeholder="25m, 1h, or leave blank", id="focus-target"
                    )
                    with Horizontal(classes="buttons"):
                        yield Button("Start focus", id="focus-start", variant="primary")
                        yield Button("Pause", id="focus-pause", disabled=True)
                        yield Button(
                            "Save", id="focus-save", variant="success", disabled=True
                        )
                        yield Button("Discard", id="focus-discard", disabled=True)
                    yield Static("RECENT SESSIONS", classes="eyebrow")
                    yield RecordTable("sessions-table")
                    yield Button(
                        "Delete selected session", id="session-delete", variant="error"
                    )
            with TabPane("Goals  F2", id="goals"):
                with VerticalScroll():
                    yield Static("Plan your next step", classes="section-title")
                    yield Static(
                        "Select a goal to focus on it or finish it. Saving an estimate starts a new accounting period.",
                        classes="hint",
                        markup=False,
                    )
                    yield RecordTable("goals-table")
                    with Horizontal(classes="buttons"):
                        yield Button("Focus on selected", id="goal-focus")
                        yield Button("Finish selected", id="goal-finish")
                        yield Button("Delete", id="goal-delete", variant="error")
                    yield Static(
                        "Create or revise an estimate", classes="section-title"
                    )
                    yield Input(placeholder="Goal title", id="goal-title")
                    yield Input(placeholder="Estimate, e.g. 4h", id="goal-estimate")
                    yield Input(
                        placeholder="Deadline YYYY-MM-DD (optional)", id="goal-deadline"
                    )
                    yield Button("Save estimate", id="goal-save", variant="primary")
            with TabPane("Reading  F3", id="reading"):
                with VerticalScroll():
                    yield Static("One page at a time", classes="section-title")
                    yield Static(
                        "Select a book to update your place or start a focus session.",
                        classes="hint",
                        markup=False,
                    )
                    yield RecordTable("books-table")
                    yield Button(
                        "Delete selected book", id="book-delete", variant="error"
                    )
                    yield Input(
                        placeholder="Current page of selected book",
                        id="book-page",
                        type="integer",
                    )
                    yield Input(
                        placeholder="Time per page, e.g. 45s (optional)", id="book-time"
                    )
                    with Horizontal(classes="buttons"):
                        yield Button(
                            "Update progress", id="book-update", variant="primary"
                        )
                        yield Button("Read selected", id="book-focus")
                    yield Static("Add to your reading list", classes="section-title")
                    yield Input(placeholder="Book title", id="book-title")
                    yield Input(
                        placeholder="Total pages", id="book-length", type="integer"
                    )
                    yield Button("Add book", id="book-add")
            with TabPane("Habits  F4", id="habits"):
                with VerticalScroll():
                    yield Static("Small things, consistently", classes="section-title")
                    yield Static(
                        "Select a habit and mark it done. Completion is recorded in your log.",
                        classes="hint",
                        markup=False,
                    )
                    yield RecordTable("habits-table")
                    yield Button(
                        "Delete selected habit", id="habit-delete", variant="error"
                    )
                    yield Button(
                        "Mark selected done today",
                        id="habit-complete",
                        variant="primary",
                    )
                    yield Static("Build a habit", classes="section-title")
                    yield Input(placeholder="Habit title", id="habit-title")
                    yield Input(
                        value="daily",
                        placeholder="daily or mon,wed,fri",
                        id="habit-frequency",
                    )
                    yield Button("Add habit", id="habit-add")
            with TabPane("Logs  F5", id="logs"):
                with VerticalScroll():
                    yield Static("Leave yourself a note", classes="section-title")
                    yield Input(
                        placeholder="Log message — Enter to save", id="log-message"
                    )
                    yield Button("Add log entry", id="log-add", variant="primary")
                    yield Static("RECENT ENTRIES", classes="eyebrow")
                    yield RecordTable("logs-table")
                    yield Button(
                        "Delete selected log", id="log-delete", variant="error"
                    )
        yield Static(
            "Tab moves between controls · F1–F5 switches views",
            id="status",
            markup=False,
        )
        yield Footer()

    async def on_mount(self) -> None:
        await self.action_reload_data()
        self.set_interval(0.25, self._update_timer)
        self.query_one("#focus-title", Input).focus()

    def on_unmount(self) -> None:
        self._io_executor.shutdown(wait=False, cancel_futures=True)

    async def _io[T](self, operation: Callable[[], T]) -> T:
        return await asyncio.get_running_loop().run_in_executor(
            self._io_executor, operation
        )

    def _input(self, identifier: str) -> str:
        return self.query_one(f"#{identifier}", Input).value

    def _set_status(self, message: str, *, error: bool = False) -> None:
        status = self.query_one("#status", Static)
        status.update(message)
        status.set_class(error, "error")

    def _table(self, identifier: str) -> RecordTable:
        return self.query_one(f"#{identifier}", RecordTable)

    def _fill_table(
        self,
        identifier: str,
        columns: Sequence[str],
        rows: Sequence[tuple[str, Sequence[str]]],
    ) -> None:
        table = self._table(identifier)
        selected: str | None = None
        if table.row_count:
            selected = table.coordinate_to_cell_key(
                table.cursor_coordinate
            ).row_key.value
        table.clear(columns=True)
        table.add_columns(*columns)
        for key, cells in rows:
            table.add_row(*(Text(cell) for cell in cells), key=key)
        if selected is not None:
            for index, (key, _) in enumerate(rows):
                if key == selected:
                    table.move_cursor(row=index)
                    break

    def _render_snapshot(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        total = sum(session["duration"] for session in snapshot.sessions)
        self.query_one("#summary", Static).update(
            f"TODAY  {format_hms(snapshot.today_seconds)}    ALL TIME  {format_hms(total)}    "
            f"SESSIONS  {len(snapshot.sessions)}\n{snapshot.data_dir}"
        )
        sessions = sorted(snapshot.sessions, key=lambda s: s["start"], reverse=True)
        self._fill_table(
            "sessions-table",
            ("Started", "Title", "Focus time", "Comment"),
            [
                (
                    s["id"],
                    (
                        s["start"].strftime("%d %b %H:%M"),
                        s["title"] or "Untitled",
                        format_hms(s["duration"]),
                        s["comment"],
                    ),
                )
                for s in sessions
            ],
        )
        self._fill_table(
            "goals-table",
            ("Title", "Estimate", "Worked", "Remaining", "Deadline", "Start by"),
            [
                (
                    g["title"],
                    (
                        g["title"],
                        g["estimate_formatted"] or "—",
                        format_hms(g["time_worked_seconds"]),
                        format_hms(
                            max(0, g["estimate_seconds"] - g["time_worked_seconds"])
                        )
                        if g["estimate_seconds"]
                        else "—",
                        str(g["deadline"] or "—"),
                        str(g["start_by"] or "—"),
                    ),
                )
                for g in snapshot.goals
            ],
        )
        self._fill_table(
            "books-table",
            ("Title", "Page", "Progress", "Time / page"),
            [
                (
                    b["title"],
                    (
                        b["title"],
                        f"{b['current_page']}/{b['length']}",
                        f"{b['current_page'] / b['length']:.0%}",
                        format_hms(b["time_per_page_seconds"])
                        if b["time_per_page_seconds"]
                        else "—",
                    ),
                )
                for b in snapshot.books
            ],
        )
        self._fill_table(
            "habits-table",
            ("Habit", "Schedule", "Today"),
            [
                (
                    h["name"],
                    (
                        h["name"],
                        h["frequency"],
                        "Done"
                        if services.habit_done_today(h["name"], snapshot.logs)
                        else "Pending"
                        if is_scheduled_today(h["frequency"])
                        else "Not scheduled",
                    ),
                )
                for h in snapshot.habits
            ],
        )
        logs = sorted(
            snapshot.logs,
            key=lambda log: str(log["timestamp"]),
            reverse=True,
        )
        self._fill_table(
            "logs-table",
            ("When", "Message"),
            [(log["id"], (str(log["timestamp"])[:16], log["message"])) for log in logs],
        )
        if self.selected_session not in {s["id"] for s in snapshot.sessions}:
            self.selected_session = None
        if self.selected_log not in {log["id"] for log in snapshot.logs}:
            self.selected_log = None
        if self.selected_goal not in {g["title"] for g in snapshot.goals}:
            self.selected_goal = None
        if self.selected_book not in {b["title"] for b in snapshot.books}:
            self.selected_book = None
        if self.selected_habit not in {h["name"] for h in snapshot.habits}:
            self.selected_habit = None
        self._sync_controls()

    async def action_reload_data(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        if self.busy:
            return
        self.busy = True
        try:
            snapshot = await self._io(services.load_snapshot)
            self._render_snapshot(snapshot)
            self._set_status(
                "Workspace refreshed · Tab to navigate · F1–F5 to switch views"
            )
        except (OSError, ValueError) as exc:
            self._set_status(f"Could not load workspace: {exc}", error=True)
        finally:
            self.busy = False
            self._sync_controls()

    async def _perform(self, operation: Callable[[], str]) -> bool:
        if self.busy:
            return False
        self.busy = True
        self._sync_controls()
        try:
            message = await self._io(operation)
        except (OSError, ValueError) as exc:
            self._set_status(str(exc), error=True)
            return False
        else:
            # A refresh failure must never turn a successful mutation into a retry.
            try:
                self._render_snapshot(await self._io(services.load_snapshot))
            except (OSError, ValueError) as exc:
                message += f" · Refresh failed: {exc}"
            self._set_status(message)
            return True
        finally:
            self.busy = False
            self._sync_controls()

    def _sync_controls(self) -> None:
        active = self.focus_session is not None
        for field in self.query(Input):
            field.disabled = self.busy or (
                active and field.id in {"focus-title", "focus-comment", "focus-target"}
            )
        for identifier in ("goal-save", "book-add", "habit-add", "log-add"):
            self.query_one(f"#{identifier}", Button).disabled = self.busy
        self.query_one("#focus-start", Button).disabled = active or self.busy
        for identifier in ("focus-pause", "focus-save", "focus-discard"):
            self.query_one(f"#{identifier}", Button).disabled = not active or self.busy
        self.query_one("#focus-pause", Button).label = (
            "Resume"
            if active and self.focus_session and self.focus_session.paused
            else "Pause"
        )
        for identifier, selection in (
            ("session-delete", self.selected_session),
            ("log-delete", self.selected_log),
            ("goal-delete", self.selected_goal),
            ("book-delete", self.selected_book),
            ("habit-delete", self.selected_habit),
            ("goal-focus", self.selected_goal),
            ("goal-finish", self.selected_goal),
            ("book-update", self.selected_book),
            ("book-focus", self.selected_book),
            ("habit-complete", self.selected_habit),
        ):
            self.query_one(f"#{identifier}", Button).disabled = (
                selection is None or self.busy
            )
        self._update_timer()

    def _update_timer(self) -> None:
        if not self.is_running:
            return
        timer = self.query_one_optional("#timer", Static)
        if timer is None:
            return  # A timer callback can arrive while the screen is unmounting.
        session = self.focus_session
        render_key = (
            (
                session.clock.seconds,
                session.paused,
                session.title,
                session.comment,
                session.target,
            )
            if session
            else (0, False, "", "", None)
        )
        if render_key == self._last_focus_render:
            return
        self._last_focus_render = render_key
        timer.update(format_hms(render_key[0]))
        self.query_one("#session-state", Static).update(
            ("Paused" if session.paused else "Focusing")
            + f" · {session.title or 'Untitled session'}"
            if session
            else "Ready when you are"
        )
        detail = "Start a session below. Pauses do not count toward focus time."
        if session:
            detail = f"Started at {session.started:%H:%M}"
            if session.target is not None:
                remaining = max(0, session.target - session.clock.seconds)
                detail += f" · Target {format_hms(session.target)} · " + (
                    f"{format_hms(remaining)} remaining"
                    if remaining
                    else "Target reached"
                )
            if session.comment:
                detail += f"\n{session.comment}"
        self.query_one("#session-detail", Static).update(detail)

    def action_show_tab(self, tab: str) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        self.query_one("#workspace", TabbedContent).active = tab
        identifier = {
            "focus": "focus-title",
            "goals": "goals-table",
            "reading": "books-table",
            "habits": "habits-table",
            "logs": "log-message",
        }[tab]
        self.query_one(f"#{identifier}").focus()

    def action_start_focus(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        if self.focus_session is not None or self.busy:
            return
        try:
            self.focus_session = services.create_focus(
                self._input("focus-title"),
                self._input("focus-comment"),
                self._input("focus-target"),
            )
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return
        self._sync_controls()
        self.query_one("#focus-pause", Button).focus()
        self._set_status("Session started · Ctrl+P pauses · Ctrl+S saves")

    def action_pause_focus(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        if self.focus_session is not None and not self.busy:
            self.focus_session.toggle_pause()
            self._sync_controls()

    async def action_save_focus(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        await self._save_focus()

    async def _save_focus(self) -> bool:
        session = self.focus_session
        if session is None or self.busy:
            return False
        session.clock.pause()
        session.paused = True
        if not await self._perform(session.save):
            self._sync_controls()
            return False
        self.focus_session = None
        self._sync_controls()
        return True

    def _prepare_focus(self, title: str) -> None:
        if self.focus_session is not None:
            self._set_status(
                "Save or discard your current session before starting another.",
                error=True,
            )
            self.action_show_tab("focus")
            return
        self.query_one("#focus-title", Input).value = title
        self.action_show_tab("focus")
        self.query_one("#focus-start", Button).focus()

    @on(DataTable.RowSelected)
    def select_record(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key is None:
            return
        snapshot = self.snapshot
        if snapshot is None:
            return
        if event.data_table.id == "sessions-table":
            self.selected_session = key
        elif event.data_table.id == "logs-table":
            self.selected_log = key
        elif event.data_table.id == "goals-table":
            self.selected_goal = key
            goal = next(g for g in snapshot.goals if g["title"] == key)
            self.query_one("#goal-title", Input).value = key
            self.query_one("#goal-estimate", Input).value = goal["estimate_formatted"]
            self.query_one("#goal-deadline", Input).value = str(goal["deadline"] or "")
        elif event.data_table.id == "books-table":
            self.selected_book = key
            book = next(b for b in snapshot.books if b["title"] == key)
            self.query_one("#book-page", Input).value = str(book["current_page"])
            self.query_one("#book-time", Input).value = (
                format_hms(book["time_per_page_seconds"])
                if book["time_per_page_seconds"]
                else ""
            )
        elif event.data_table.id == "habits-table":
            self.selected_habit = key
        self._sync_controls()

    @on(Input.Submitted, "#log-message")
    async def submit_log(self) -> None:
        await self._add_log()

    async def _add_log(self) -> None:
        message = self._input("log-message")
        if await self._perform(lambda: services.add_log(message)):
            self.query_one("#log-message", Input).value = ""

    @on(Button.Pressed)
    async def handle_button(self, event: Button.Pressed) -> None:
        identifier = event.button.id
        if identifier in {
            "session-delete",
            "log-delete",
            "goal-delete",
            "book-delete",
            "habit-delete",
        }:
            if self.busy or isinstance(self.screen, ModalScreen):
                return
            kind = identifier.removesuffix("-delete")
            selection = {
                "session": self.selected_session,
                "log": self.selected_log,
                "goal": self.selected_goal,
                "book": self.selected_book,
                "habit": self.selected_habit,
            }[kind]
            if selection is not None:

                async def confirmed(answer: bool | None) -> None:
                    if answer:
                        await self._perform(
                            lambda: storage.delete_record(kind, selection)
                        )

                self.push_screen(DeleteDecision(f"{kind}: {selection}"), confirmed)
        elif identifier == "focus-start":
            self.action_start_focus()
        elif identifier == "focus-pause":
            self.action_pause_focus()
        elif identifier == "focus-save":
            await self._save_focus()
        elif identifier == "focus-discard":
            self.focus_session = None
            self._sync_controls()
            self._set_status("Session discarded · Nothing saved")
        elif identifier == "goal-save":
            title, estimate, deadline = (
                self._input(field)
                for field in ("goal-title", "goal-estimate", "goal-deadline")
            )
            await self._perform(lambda: services.save_goal(title, estimate, deadline))
        elif identifier == "goal-finish" and self.selected_goal is not None:
            title = self.selected_goal
            await self._perform(lambda: services.finish_goal(title))
        elif identifier == "goal-focus" and self.selected_goal is not None:
            self._prepare_focus(self.selected_goal)
        elif identifier == "book-add":
            title, length = self._input("book-title"), self._input("book-length")
            if await self._perform(lambda: services.add_book(title, length)):
                self.query_one("#book-title", Input).value = ""
                self.query_one("#book-length", Input).value = ""
        elif identifier == "book-update" and self.selected_book is not None:
            title, page, timing = (
                self.selected_book,
                self._input("book-page"),
                self._input("book-time"),
            )
            await self._perform(lambda: services.update_book(title, page, timing))
        elif identifier == "book-focus" and self.selected_book is not None:
            self._prepare_focus(self.selected_book)
        elif identifier == "habit-add":
            title, frequency = (
                self._input("habit-title"),
                self._input("habit-frequency"),
            )
            if await self._perform(lambda: services.add_habit(title, frequency)):
                self.query_one("#habit-title", Input).value = ""
        elif identifier == "habit-complete" and self.selected_habit is not None:
            title = self.selected_habit
            await self._perform(lambda: services.complete_habit(title))
        elif identifier == "log-add":
            await self._add_log()

    @override
    async def action_quit(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        if self.busy:
            self._set_status(
                "Finishing the current operation; try quitting again in a moment."
            )
            return
        if self.focus_session is None:
            self.exit()
        else:
            self.push_screen(SessionDecision(), self._resolve_quit)

    async def _resolve_quit(self, decision: str | None) -> None:
        if decision == "discard":
            self.focus_session = None
            self.exit()
        elif decision == "save" and await self._save_focus():
            self.exit()
