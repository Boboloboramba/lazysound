"""Persistent error log screen — press E to view decode failures."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static

from lazysound.core.errors import get_recent, load_from_file, clear, DEFAULT_ERROR_LOG, LoggedError


class ErrorLogScreen(ModalScreen):
    DEFAULT_CSS = """
    ErrorLogScreen {
        align: center middle;
        background: rgba(0,0,0,0.65);
    }
    ErrorLogScreen #err-box {
        width: 110;
        height: 36;
        max-height: 88%;
        background: $surface;
        border: thick $error;
        padding: 1 1;
    }
    ErrorLogScreen #err-title {
        height: 1;
        text-style: bold;
        color: $error;
        content-align: center middle;
    }
    ErrorLogScreen #err-subtitle {
        height: 1;
        color: $text-muted;
        content-align: center middle;
    }
    ErrorLogScreen DataTable {
        height: 1fr;
        margin: 1 0;
    }
    ErrorLogScreen #err-controls {
        height: 3;
        align: center middle;
    }
    ErrorLogScreen Button {
        margin: 0 1;
        min-width: 12;
    }
    ErrorLogScreen #err-detail {
        height: 3;
        border: round $secondary;
        padding: 0 1;
        color: $warning;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("j", "cursor_down", "Down", show=False, priority=True),
        Binding("k", "cursor_up", "Up", show=False, priority=True),
        Binding("c", "clear", "Clear"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="err-box"):
            yield Static("⚠ Error Log — recent decode / IO failures", id="err-title")
            yield Static("", id="err-subtitle")
            yield DataTable(id="err-table")
            yield Static("Select a row to see details below", id="err-detail")
            with Horizontal(id="err-controls"):
                yield Button("Clear Log", id="btn-clear", variant="warning")
                yield Button("Open Folder", id="btn-open", variant="primary")
                yield Button("Close", id="btn-close", variant="primary")
            yield Static("j/k navigate • Enter open folder • c clear • Esc/q close", id="err-help")

    def on_mount(self) -> None:
        table = self.query_one("#err-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Time", "Context", "File", "Error")
        self._refresh()

    def _refresh(self) -> None:
        # prefer in-memory, fallback to file
        errors = get_recent(200)
        if not errors:
            errors = load_from_file(200)
        table = self.query_one("#err-table", DataTable)
        table.clear()
        for e in reversed(errors):  # newest first
            # truncate path to last 2 components + error to 60 chars
            try:
                p = Path(e.path)
                short_path = str(p) if len(str(p)) < 50 else f"…/{p.parent.name}/{p.name}"
            except Exception:
                short_path = e.path
            table.add_row(e.pretty_time(), e.context or "-", short_path, e.error[:80])
        # store for detail view
        self._errors = list(reversed(errors))
        try:
            cnt = len(errors)
            loc = str(DEFAULT_ERROR_LOG)
            self.query_one("#err-subtitle", Static).update(f"{cnt} recent errors • log file: {loc} • {len([e for e in errors if e.context=='decode'])} decode failures")
            if cnt == 0:
                self.query_one("#err-detail", Static).update("No errors logged — if you saw 'can't decode' it was likely the HTML 404 placeholder at ~/Documents/WebProjects/OpenCodeTest/public/meow.mp3 (315 bytes). Delete that file if you don't need it.")
            else:
                self.query_one("#err-detail", Static).update("Select a row to see full path and error")
        except Exception:
            pass
        # update detail for first row
        if self._errors:
            self._show_detail(0)

    def _show_detail(self, row: int) -> None:
        if not hasattr(self, "_errors") or not (0 <= row < len(self._errors)):
            return
        e = self._errors[row]
        try:
            self.query_one("#err-detail", Static).update(f"{e.pretty_date()}  [{e.context}]  {e.path}  →  {e.error}")
        except Exception:
            pass

    @on(DataTable.RowHighlighted, "#err-table")
    def on_highlight(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is not None:
            self._show_detail(event.cursor_row)

    @on(DataTable.RowSelected, "#err-table")
    def on_select(self, event: DataTable.RowSelected) -> None:
        if event.cursor_row is not None:
            self._show_detail(event.cursor_row)

    @on(Button.Pressed, "#btn-clear")
    def on_clear(self) -> None:
        self.action_clear()

    @on(Button.Pressed, "#btn-open")
    def on_open(self) -> None:
        self.action_open()

    @on(Button.Pressed, "#btn-close")
    def on_close(self) -> None:
        self.action_close()

    def action_clear(self) -> None:
        clear()
        self.app.notify("Error log cleared", severity="information")
        self._refresh()

    def action_open(self) -> None:
        try:
            table = self.query_one("#err-table", DataTable)
            row = table.cursor_row
            if row is None or not (0 <= row < len(self._errors)):
                return
            e = self._errors[row]
            p = Path(e.path)
            # open parent folder in MainScreen
            # dismiss with path
            self.dismiss(p.parent if p.is_file() else p)
        except Exception:
            self.dismiss(None)

    def action_cursor_down(self) -> None:
        try:
            self.query_one("#err-table", DataTable).action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        try:
            self.query_one("#err-table", DataTable).action_cursor_up()
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key in ("escape", "q"):
            self.dismiss(None)
