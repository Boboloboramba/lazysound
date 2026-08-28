"""Main application screen with 3-pane layout."""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static

from lazysound.core.scanner import AudioFile, scan_directory
from lazysound.core.metadata import AudioMetadata, read_metadata
from lazysound.core.search import SearchEngine, SearchQuery
from lazysound.widgets.file_browser import FileBrowser, DirectoryChanged
from lazysound.widgets.file_list import FileList, FileSelected
from lazysound.widgets.metadata_panel import MetadataPanel
from lazysound.widgets.search import SearchBar, SearchChanged


class MainScreen(Screen):
    """Main 3-pane screen: directory tree, file list, metadata preview."""

    CSS = """
    MainScreen Horizontal {
        height: 1fr;
    }
    #left-pane {
        width: 30;
        min-width: 20;
    }
    #center-pane {
        width: 1fr;
        min-width: 30;
    }
    #right-pane {
        width: 1fr;
        min-width: 40;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("b", "batch_edit", "Batch Edit"),
        Binding("r", "refresh", "Refresh"),
        Binding("g", "goto", "Go To Directory"),
    ]

    current_path: reactive[Path] = reactive(Path.home())
    selected_file: reactive[AudioFile | None] = reactive(None)
    search_engine: SearchEngine = SearchEngine()

    def __init__(self, start_path: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        if start_path:
            self.current_path = start_path

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="left-pane"):
                yield FileBrowser(start_path=self.current_path, id="file-browser")
            with Vertical(id="center-pane"):
                yield SearchBar(id="search-bar")
                yield FileList(start_path=self.current_path, id="file-list")
            with Vertical(id="right-pane"):
                yield MetadataPanel(id="metadata-panel")
        yield Footer()

    @on(DirectoryChanged)
    def on_directory_changed(self, event: DirectoryChanged) -> None:
        self.current_path = event.path
        self.query_one("#file-list", FileList).current_path = event.path

    @on(FileSelected)
    def on_file_selected(self, event: FileSelected) -> None:
        self.selected_file = event.audio_file
        self.query_one("#metadata-panel", MetadataPanel).current_file = event.audio_file

    @on(SearchChanged)
    def on_search_changed(self, event: SearchChanged) -> None:
        """Filter the file list based on search query."""
        file_list = self.query_one("#file-list", FileList)
        if not event.query.text.strip():
            file_list._load_files()
            return

        # Filter files based on query
        filtered = self.search_engine.search(file_list.files, event.query)
        # Update the table
        table = file_list.query_one("#file-table")
        table.clear()
        file_list.files = [r.audio_file for r in filtered]
        for r in filtered:
            table.add_row(
                r.audio_file.path.stem,
                r.audio_file.format_name,
                r.audio_file.size_display,
            )

    def action_refresh(self) -> None:
        self.query_one("#file-list", FileList)._load_files()

    def action_goto(self) -> None:
        self.app.push_screen(GotoScreen(self.current_path))

    def action_batch_edit(self) -> None:
        file_list = self.query_one("#file-list", FileList)
        if file_list.files:
            self.app.push_screen(BatchEditScreen(file_list.files))


class GotoScreen(Screen):
    """Screen for navigating to a directory by path."""

    CSS = """
    GotoScreen {
        align: center middle;
    }
    GotoScreen Vertical {
        width: 60;
        height: auto;
        padding: 2;
        border: thick $primary;
        background: $surface;
    }
    GotoScreen Input {
        margin: 1 0;
    }
    GotoScreen Horizontal {
        margin-top: 1;
        align: right middle;
    }
    GotoScreen Button {
        margin: 0 1;
    }
    """

    def __init__(self, current_path: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.current_path = current_path

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Go to directory:")
            yield Input(value=str(self.current_path), id="path-input", placeholder="/path/to/audio")
            with Horizontal():
                yield Button("Go", id="btn-go", variant="primary")
                yield Button("Cancel", id="btn-cancel")

    @on(Button.Pressed, "#btn-go")
    def on_go(self) -> None:
        input = self.query_one("#path-input", Input)
        path = Path(input.value)
        if path.is_dir():
            self.dismiss(path)
        else:
            self.app.notify(f"Not a directory: {input.value}", severity="error")

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)


from textual.widgets import Button, Input


class BatchEditScreen(Screen):
    """Screen for batch editing metadata across multiple files."""

    CSS = """
    BatchEditScreen {
        align: center middle;
    }
    BatchEditScreen Vertical {
        width: 70;
        height: auto;
        max-height: 80%;
        padding: 2;
        border: thick $warning;
        background: $surface;
    }
    BatchEditScreen Select {
        margin: 1 0;
    }
    BatchEditScreen Input {
        margin: 1 0;
    }
    BatchEditScreen Horizontal {
        margin-top: 1;
        align: right middle;
    }
    BatchEditScreen Button {
        margin: 0 1;
    }
    .file-list-section {
        height: auto;
        max-height: 15;
        overflow-y: auto;
        border: round $secondary;
        padding: 1;
        margin: 1 0;
    }
    """

    def __init__(self, files: list[AudioFile], **kwargs) -> None:
        super().__init__(**kwargs)
        self.files = files

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"Batch Edit ({len(self.files)} files)")
            yield Static("Files to edit:", classes="section-header")
            with Vertical(classes="file-list-section"):
                for af in self.files[:20]:
                    yield Static(f"  {af.path.name} ({af.format_name})")
                if len(self.files) > 20:
                    yield Static(f"  ... and {len(self.files) - 20} more")

            yield Label("Field to edit:")
            yield Select(
                [
                    ("Title", "title"),
                    ("Artist", "artist"),
                    ("Album", "album"),
                    ("Album Artist", "albumartist"),
                    ("Genre", "genre"),
                    ("Date", "date"),
                    ("Composer", "composer"),
                    ("Track #", "tracknumber"),
                ],
                value="title",
                id="batch-field",
                allow_blank=False,
            )

            yield Label("Value:")
            yield Input(placeholder="New value", id="batch-value")

            with Horizontal():
                yield Button("Apply", id="btn-apply", variant="success")
                yield Button("Cancel", id="btn-cancel")

    @on(Button.Pressed, "#btn-apply")
    def on_apply(self) -> None:
        from lazysound.core.batch import batch_set_field

        field = str(self.query_one("#batch-field", Select).value)
        value = self.query_one("#batch-value", Input).value

        if not value:
            self.app.notify("Please enter a value", severity="warning")
            return

        result = batch_set_field(self.files, field, value)
        self.app.notify(f"Batch edit: {result.summary}", severity="success" if result.error_count == 0 else "warning")
        self.dismiss(True)

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)
