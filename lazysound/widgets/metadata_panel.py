"""Metadata display and edit panel widget."""

from __future__ import annotations

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
    #button-bar {
        dock: bottom;
        height: 3;
        width: 1fr;
        padding: 0 1;
        background: $panel;
        align: center middle;
    }
    #button-bar Button {
        margin: 0 1;
        min-width: 5;
        width: 1fr;
        max-width: 12;
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

    @on(Button.Pressed, "#btn-save")
    def on_save_pressed(self) -> None:
        if self.metadata:
            error = write_metadata(self.metadata)
            if error:
                self.app.notify(f"Save error: {error}", severity="error")
            else:
                self.app.notify("Metadata saved successfully", severity="success")
                # keep search index in sync
                try:
                    from lazysound.core.scanner import AudioFile as _AF
                    from lazysound.core.metadata import read_metadata as _rm
                    main = None
                    if self.screen and self.screen.__class__.__name__ == "MainScreen":
                        main = self.screen
                    else:
                        for s in self.app.screen_stack:
                            if s.__class__.__name__ == "MainScreen":
                                main = s
                                break
                    if main is not None and hasattr(main, "search_engine"):
                        try:
                            fresh = _rm(_AF(path=self.metadata.path))
                        except Exception:
                            fresh = self.metadata
                        main.search_engine.cache_metadata(fresh.path, fresh)
                        try:
                            main.search_engine._haystack_cache.pop(fresh.path, None)
                        except Exception:
                            pass
                except Exception:
                    pass
            self.editing = False

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel_pressed(self) -> None:
        self.editing = False
        if self.current_file:
            self._load_metadata(self.current_file)

    async def watch_current_file(self, file: AudioFile | None) -> None:
        if not self.is_mounted:
            return
        if file:
            # show loading immediately
            header = self.query_one("#file-header", Static)
            header.update(f"Loading {file.path.name}…")
            self._load_metadata(file)
        else:
            self.metadata = None

    async def watch_metadata(self, meta: AudioMetadata | None) -> None:
        await self._refresh_display()

    async def watch_editing(self, editing: bool) -> None:
        await self._refresh_display()

    @work(thread=True)
    def _load_metadata(self, file: AudioFile) -> None:
        meta = read_metadata(file)
        # use call_from_thread to safely set reactive on main thread
        self.app.call_from_thread(lambda: setattr(self, "metadata", meta))

    async def _refresh_display(self) -> None:
        # This is now async and properly awaits mount/remove to avoid duplication
        try:
            header = self.query_one("#file-header", Static)
            tags_container = self.query_one("#tags-container", Vertical)
            tech_container = self.query_one("#tech-container", Vertical)
            waveform = self.query_one("#waveform-display", Static)
        except Exception:
            return

        # Clear existing — await to ensure completed before re-mounting
        try:
            await tags_container.remove_children()
            await tech_container.remove_children()
        except Exception:
            pass

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
        await tags_container.mount(Static("Metadata Tags", classes="section-header"))
        for field_key, field_label in STANDARD_FIELDS:
            value = meta.tags.get(field_key, "")
            row = Horizontal(classes="meta-row")
            await tags_container.mount(row)
            await row.mount(Label(field_label, classes="meta-label"))
            if self.editing:
                await row.mount(Input(value=value, placeholder=field_label, classes="meta-input", id=f"edit-{field_key}"))
            else:
                display = value if value else "-"
                await row.mount(Static(display, classes="meta-value"))

        # Technical info (read-only)
        await tech_container.mount(Static("Technical Info", classes="section-header"))
        for field_key, field_label in TECH_FIELDS:
            value = meta.technical.get(field_key, "")
            row2 = Horizontal(classes="meta-row")
            await tech_container.mount(row2)
            await row2.mount(Label(field_label, classes="meta-label"))
            await row2.mount(Static(value if value else "-", classes="meta-value"))

        if meta.error:
            await tags_container.mount(Static(f"Warning: {meta.error}", classes="meta-row"))

    @on(Input.Changed)
    def on_input_changed(self, event: Input.Changed) -> None:
        """Sync input changes back to metadata."""
        if not self.metadata or not self.editing:
            return
        # only handle our edit inputs
        if not event.input.id or not event.input.id.startswith("edit-"):
            return
        field_key = event.input.id.replace("edit-", "")
        self.metadata.set_tag(field_key, event.value)
