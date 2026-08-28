"""Library screen — system-wide folders containing audio/DAW files."""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Static

from lazysound.core.library import AudioLibrary, FolderEntry

class LibraryFolderSelected(Message):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

class LibraryScreen(ModalScreen):
    DEFAULT_CSS = """
    LibraryScreen {
        align: center middle;
        background: rgba(0,0,0,0.6);
    }
    LibraryScreen #lib-box {
        width: 110;
        height: 38;
        max-height: 88%;
        background: $surface;
        border: thick $primary;
        padding: 1 1;
    }
    LibraryScreen #lib-title {
        height: 1;
        text-style: bold;
        color: $warning;
        content-align: center middle;
    }
    LibraryScreen #lib-subtitle {
        height: 1;
        color: $text-muted;
        content-align: center middle;
    }
    LibraryScreen DataTable {
        height: 1fr;
        margin: 1 0;
    }
    LibraryScreen #lib-controls {
        height: 3;
        align: center middle;
    }
    LibraryScreen Button {
        margin: 0 1;
        min-width: 10;
    }
    LibraryScreen #filter-input {
        width: 1fr;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("r", "rescan", "Rescan"),
        Binding("enter", "open", "Open"),
        Binding("j", "cursor_down", "Down", show=False, priority=True),
        Binding("k", "cursor_up", "Up", show=False, priority=True),
        Binding("G", "cursor_bottom", "Bottom", show=False, priority=True),
        Binding("home", "cursor_top", "Top", show=False, priority=True),
    ]

    def __init__(self, library: AudioLibrary, **kwargs) -> None:
        super().__init__(**kwargs)
        self.library = library
        self._filtered: list[FolderEntry] = []
        self._filter_text: str = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="lib-box"):
            yield Static("Library — Folders with sound / music / DAW projects", id="lib-title")
            yield Static("", id="lib-subtitle")
            with Horizontal():
                yield Label("Filter:")
                yield Input(placeholder="filter by path or format (fuzzy)", id="filter-input")
                yield Button("Rescan", id="btn-rescan", variant="warning")
                yield Button("Open", id="btn-open", variant="success")
                yield Button("Close", id="btn-close")
            yield DataTable(id="lib-table")
            yield Static("j/k navigate • Enter open folder • r rescan • / filter • Esc close", id="lib-help")

    def on_mount(self) -> None:
        table = self.query_one("#lib-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Path", "Audio", "DAW", "Size", "Formats", "Sample")
        self.query_one("#filter-input", Input).focus()
        self._refresh_table()

    def _refresh_table(self) -> None:
        folders = self.library.get_folders()
        # apply filter if any
        if self._filter_text.strip():
            q = self._filter_text.lower()
            folders = [f for f in folders if q in f.path.lower() or q in " ".join(f.formats).lower()]
        self._filtered = folders
        try:
            table = self.query_one("#lib-table", DataTable)
            table.clear()
            for fe in folders:
                table.add_row(
                    fe.path,
                    str(fe.audio_count),
                    str(fe.daw_count),
                    fe.pretty_size(),
                    ", ".join(fe.formats[:4]),
                    ", ".join(fe.sample_files[:2]),
                )
            # subtitle
            self.query_one("#lib-subtitle", Static).update(
                f"{len(folders)} folders • {sum(f.audio_count for f in folders)} audio files • last scan {self._age_str()} • {self.library.cache_file}"
            )
        except Exception:
            pass

    def _age_str(self) -> str:
        import time
        if not self.library.state.last_full_scan:
            return "never"
        age = time.time() - self.library.state.last_full_scan
        if age < 3600:
            return f"{int(age/60)}m ago"
        if age < 86400:
            return f"{int(age/3600)}h ago"
        return f"{int(age/86400)}d ago"

    @on(Input.Changed, "#filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        self._filter_text = event.value
        self._refresh_table()

    @on(DataTable.RowSelected, "#lib-table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_open()

    @on(Button.Pressed, "#btn-rescan")
    def on_rescan(self) -> None:
        self.action_rescan()

    @on(Button.Pressed, "#btn-open")
    def on_open_btn(self) -> None:
        self.action_open()

    @on(Button.Pressed, "#btn-close")
    def on_close_btn(self) -> None:
        self.action_close()

    def action_open(self) -> None:
        try:
            table = self.query_one("#lib-table", DataTable)
            row = table.cursor_row
            if row is None or not (0 <= row < len(self._filtered)):
                # if nothing selected, try first
                if self._filtered:
                    row = 0
                else:
                    return
            fe = self._filtered[row]
            self.dismiss(Path(fe.path))
        except Exception:
            pass

    def action_rescan(self) -> None:
        self.app.notify("Rescanning system for audio folders…", severity="information")
        self._run_rescan()

    @work(thread=True)
    def _run_rescan(self) -> None:
        def _prog(scanned, found, cur):
            # throttle
            if scanned % 400 == 0:
                try:
                    self.app.call_from_thread(lambda: self.query_one("#lib-subtitle", Static).update(f"Scanning… {scanned} dirs, {found} folders — {cur}"))
                except Exception:
                    pass
        try:
            self.library.scan_system(progress_cb=_prog, force=True)
        except Exception as e:
            self.app.call_from_thread(lambda: self.app.notify(f"Scan error: {e}", severity="error"))
            return
        self.app.call_from_thread(self._refresh_table)
        self.app.call_from_thread(lambda: self.app.notify(f"Scan done — {len(self.library.get_folders())} folders", severity="success"))

    def action_cursor_down(self) -> None:
        try:
            self.query_one("#lib-table", DataTable).action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        try:
            self.query_one("#lib-table", DataTable).action_cursor_up()
        except Exception:
            pass

    def action_cursor_top(self) -> None:
        try:
            t = self.query_one("#lib-table", DataTable)
            t.move_cursor(row=0)
        except Exception:
            pass

    def action_cursor_bottom(self) -> None:
        try:
            t = self.query_one("#lib-table", DataTable)
            t.move_cursor(row=max(0, t.row_count - 1))
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss(None)
