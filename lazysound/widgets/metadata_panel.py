"""Metadata display and edit panel widget."""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, Input, Label, Button

from lazysound.core.metadata import AudioMetadata, read_metadata, write_metadata, STANDARD_FIELDS, TECH_FIELDS
from lazysound.core.scanner import AudioFile
from lazysound.widgets.waveform import render_waveform


class MetadataPanel(Widget):
    """Panel displaying audio file metadata with inline editing."""

    DEFAULT_CSS = """
    MetadataPanel {
        height: 1fr;
        width: 1fr;
        border: solid $success;
    }
    MetadataPanel > Static {
        dock: top;
        padding: 0 1;
        background: $accent;
        color: $text;
        text-style: bold;
    }
    MetadataPanel ScrollableContainer {
        height: 1fr;
    }
    .meta-row {
        height: auto;
        padding: 0 1;
    }
    .meta-label {
        width: 15;
        text-style: bold;
        color: $primary;
    }
    .meta-value {
        width: 1fr;
    }
    .meta-input {
        width: 1fr;
    }
    .waveform-container {
        height: auto;
        padding: 1;
        margin: 1 0;
        border: round $secondary;
    }
    .tech-section {
        height: auto;
        padding: 1;
        margin-top: 1;
        border: round $secondary;
    }
    .section-header {
        text-style: bold;
        color: $accent;
        padding: 0 1;
    }
    .file-header {
        padding: 1 1;
        text-style: bold;
        color: $warning;
    }
    """

    current_file: reactive[AudioFile | None] = reactive(None)
    metadata: reactive[AudioMetadata | None] = reactive(None)
    editing: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Metadata", id="panel-header")
            with ScrollableContainer(id="meta-scroll"):
                yield Static("No file selected", id="file-header")
                yield Static("", id="waveform-display")
                with Vertical(id="tags-container"):
                    pass
                with Vertical(id="tech-container"):
                    pass
            with Horizontal(id="button-bar"):
                yield Button("Edit", id="btn-edit", variant="primary")
                yield Button("Save", id="btn-save", variant="success")
                yield Button("Cancel", id="btn-cancel", variant="warning")

    @on(Button.Pressed, "#btn-edit")
    def on_edit_pressed(self) -> None:
        self.editing = True
        self._refresh_display()

    @on(Button.Pressed, "#btn-save")
    def on_save_pressed(self) -> None:
        if self.metadata:
            error = write_metadata(self.metadata)
            if error:
                self.app.notify(f"Save error: {error}", severity="error")
            else:
                self.app.notify("Metadata saved successfully", severity="success")
            self.editing = False
            self._refresh_display()

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel_pressed(self) -> None:
        self.editing = False
        if self.current_file:
            self._load_metadata(self.current_file)
        self._refresh_display()

    def watch_current_file(self, file: AudioFile | None) -> None:
        if not self.is_mounted:
            return
        if file:
            self._load_metadata(file)
        else:
            self.metadata = None
        self._refresh_display()

    @work(thread=True)
    def _load_metadata(self, file: AudioFile) -> None:
        meta = read_metadata(file)
        self.app.call_from_thread(lambda: self._set_metadata(meta))

    def _set_metadata(self, meta: AudioMetadata) -> None:
        self.metadata = meta
        self._refresh_display()

    def _refresh_display(self) -> None:
        header = self.query_one("#file-header", Static)
        tags_container = self.query_one("#tags-container", Vertical)
        tech_container = self.query_one("#tech-container", Vertical)
        waveform = self.query_one("#waveform-display", Static)

        # Clear existing
        tags_container.remove_children()
        tech_container.remove_children()

        if not self.metadata:
            header.update("No file selected")
            waveform.update("")
            return

        meta = self.metadata
        header.update(f"{meta.path.name}  ({meta.format_name})")

        # Waveform
        try:
            wf_text = render_waveform(meta.path, width=70, height=6)
            waveform.update(wf_text)
        except Exception:
            waveform.update("")

        # Editable tags
        tags_container.mount(Static("Metadata Tags", classes="section-header"))
        for field_key, field_label in STANDARD_FIELDS:
            value = meta.tags.get(field_key, "")
            row = Horizontal(classes="meta-row")
            tags_container.mount(row)
            row.mount(Label(field_label, classes="meta-label"))
            if self.editing:
                inp = Input(value=value, placeholder=field_label, classes="meta-input", id=f"edit-{field_key}")
                row.mount(inp)
            else:
                display = value if value else "-"
                row.mount(Static(display, classes="meta-value"))

        # Technical info (read-only)
        tech_container.mount(Static("Technical Info", classes="section-header"))
        for field_key, field_label in TECH_FIELDS:
            value = meta.technical.get(field_key, "")
            row2 = Horizontal(classes="meta-row")
            tech_container.mount(row2)
            row2.mount(Label(field_label, classes="meta-label"))
            row2.mount(Static(value if value else "-", classes="meta-value"))

        if meta.error:
            tags_container.mount(Static(f"Warning: {meta.error}", classes="meta-row"))

    @on(Input.Changed)
    def on_input_changed(self, event: Input.Changed) -> None:
        """Sync input changes back to metadata."""
        if not self.metadata or not self.editing:
            return
        field_key = event.input.id.replace("edit-", "")
        self.metadata.set_tag(field_key, event.value)
