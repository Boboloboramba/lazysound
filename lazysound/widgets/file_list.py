"""Audio file list table widget."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Static

from lazysound.core.scanner import AudioFile, scan_directory


class FileList(Widget):
    """A sortable table of audio files in the current directory."""

    DEFAULT_CSS = """
    FileList {
        height: 1fr;
        width: 1fr;
        border: solid $secondary;
    }
    FileList > Static {
        dock: top;
        padding: 0 1;
        background: $accent;
        color: $text;
        text-style: bold;
    }
    FileList DataTable {
        height: 1fr;
    }
    """

    current_path: reactive[Path] = reactive(Path.home(), always_update=True)
    files: list[AudioFile] = []

    def __init__(self, start_path: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._start_path = start_path

    def compose(self) -> ComposeResult:
        yield Static("Audio Files")
        yield DataTable(id="file-table")

    def on_mount(self) -> None:
        table = self.query_one("#file-table", DataTable)
        table.add_columns("Name", "Format", "Size")
        table.cursor_type = "row"
        if self._start_path:
            self.current_path = self._start_path
            self._start_path = None
        self._load_files()

    def watch_current_path(self, path: Path) -> None:
        if not self.is_mounted:
            return
        self._load_files()

    def _load_files(self) -> None:
        table = self.query_one("#file-table", DataTable)
        table.clear()
        self.files = []

        if not self.current_path.exists():
            return

        result = scan_directory(self.current_path, recursive=False)
        self.files = result.audio_files

        for af in self.files:
            table.add_row(
                af.path.stem,
                af.format_name,
                af.size_display,
            )
        # Auto-select first file so Metadata side panel is populated immediately
        if self.files:
            try:
                table.move_cursor(row=0)
                # RowHighlighted will fire and post FileSelected, but also post directly for robustness
                self.post_message(FileSelected(self.files[0]))
            except Exception:
                pass

    def set_files(self, files: list[AudioFile]) -> None:
        """Display an arbitrary list of files (used for deep search / recursive view)."""
        try:
            table = self.query_one("#file-table", DataTable)
        except Exception:
            self.files = files
            return
        table.clear()
        self.files = files
        for af in files:
            # show relative path hint when deep
            rel = ""
            try:
                if af.path.parent != self.current_path:
                    rel = f" ({af.path.parent.name})"
            except Exception:
                pass
            display = af.path.stem + rel
            if len(display) > 32:
                display = display[:31] + "…"
            table.add_row(display, af.format_name, af.size_display)
        # Auto-select first file so side panel populates (fixes empty Metadata Tags)
        if self.files:
            try:
                table.move_cursor(row=0)
                # Ensure highlight posts FileSelected even if cursor was already at 0
                # DataTable may not fire RowHighlighted when moving to same row, so post directly
                self.post_message(FileSelected(self.files[0]))
            except Exception:
                pass

    def get_selected_file(self) -> AudioFile | None:
        """Get the currently selected AudioFile."""
        table = self.query_one("#file-table", DataTable)
        if table.cursor_row is not None and 0 <= table.cursor_row < len(self.files):
            return self.files[table.cursor_row]
        return None

    def get_selected_files(self) -> list[AudioFile]:
        """Get all selected AudioFiles (for batch operations)."""
        table = self.query_one("#file-table", DataTable)
        selected = []
        for row_idx in table.cursor_type:
            pass  # Multi-select not directly supported in basic DataTable
        # Return single selection for now
        single = self.get_selected_file()
        return [single] if single else []

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Post message when a file is selected (Enter/click)."""
        af = self.get_selected_file()
        if af:
            self.post_message(FileSelected(af))

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Live preview on cursor move (vim j/k)."""
        # RowHighlighted fires on every cursor move; use for vim navigation
        if event.cursor_row is None:
            return
        if 0 <= event.cursor_row < len(self.files):
            af = self.files[event.cursor_row]
            self.post_message(FileSelected(af))


class FileSelected(Message):
    """Message posted when a file is selected in the list."""

    def __init__(self, audio_file: AudioFile) -> None:
        super().__init__()
        self.audio_file = audio_file
