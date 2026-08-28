"""Audio file list table widget."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
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
        if start_path:
            self.current_path = start_path

    def compose(self) -> ComposeResult:
        yield Static("Audio Files")
        yield DataTable(id="file-table")

    def on_mount(self) -> None:
        table = self.query_one("#file-table", DataTable)
        table.add_columns("Name", "Format", "Size")
        table.cursor_type = "row"
        self._load_files()

    def watch_current_path(self, path: Path) -> None:
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
        """Post message when a file is selected."""
        af = self.get_selected_file()
        if af:
            self.post_message(FileSelected(af))


class FileSelected:
    """Message posted when a file is selected in the list."""

    def __init__(self, audio_file: AudioFile) -> None:
        self.audio_file = audio_file
