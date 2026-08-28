"""Editable metadata tree view — opened via 'i'."""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, Tree

from lazysound.core.metadata import AudioMetadata, read_metadata, write_metadata, STANDARD_FIELDS, TECH_FIELDS
from lazysound.core.scanner import AudioFile


def _build_tree_data(meta: AudioMetadata) -> list[tuple[str, list[tuple[str, str, bool, str]]]]:
    """Return sections: (section_title, [(key, label, writable, value)])"""
    sections: list[tuple[str, list[tuple[str, str, bool, str]]]] = []

    # Common (standard fields)
    common: list[tuple[str, str, bool, str]] = []
    for k, label in STANDARD_FIELDS:
        common.append((k, label, True, meta.tags.get(k, "")))
    sections.append(("Common Tags (editable)", common))

    # All writable tags (including custom, not only standard)
    all_editable: list[tuple[str, str, bool, str]] = []
    for k, v in sorted(meta.tags.items()):
        # avoid duplicate if already in common and value same; still show
        all_editable.append((k, k, True, v))
    sections.append(("All Tags (editable)", all_editable))

    # Technical (read-only)
    tech: list[tuple[str, str, bool, str]] = []
    for k, label in TECH_FIELDS:
        tech.append((k, label, False, meta.technical.get(k, "")))
    # add file system extra
    tech.append(("path", "Path", False, str(meta.path)))
    try:
        st = meta.path.stat()
        tech.append(("size_bytes", "Size (bytes)", False, str(st.st_size)))
        tech.append(("modified", "Modified", False, str(st.st_mtime)))
    except Exception:
        pass
    if meta.error:
        tech.append(("error", "Error", False, meta.error))
    sections.append(("Technical / File (read-only)", tech))

    # Raw
    raw: list[tuple[str, str, bool, str]] = []
    for k, vals in sorted(meta.raw_tags.items()):
        raw.append((k, k, False, ", ".join(vals)))
    if raw:
        sections.append(("Raw Tags", raw))

    return sections


class MetadataInfoScreen(ModalScreen):
    """Dedicated editable tree view for a file's metadata. Hit 'i' to open."""

    DEFAULT_CSS = """
    MetadataInfoScreen {
        align: center middle;
        background: rgba(0,0,0,0.65);
    }
    MetadataInfoScreen #info-box {
        width: 92;
        height: 36;
        max-height: 92%;
        background: $surface;
        border: thick $primary;
        padding: 1 1;
    }
    MetadataInfoScreen #info-title {
        height: 1;
        text-style: bold;
        color: $warning;
        content-align: center middle;
    }
    MetadataInfoScreen #info-subtitle {
        height: 1;
        color: $text-muted;
        content-align: center middle;
    }
    MetadataInfoScreen Tree {
        height: 1fr;
        border: round $secondary;
        margin: 1 0;
    }
    MetadataInfoScreen #edit-row {
        height: 3;
        align: center middle;
    }
    MetadataInfoScreen Input {
        margin: 0 1;
    }
    MetadataInfoScreen #key-input {
        width: 22;
    }
    MetadataInfoScreen #value-input {
        width: 1fr;
    }
    MetadataInfoScreen #help {
        height: 1;
        color: $text-muted;
        text-style: italic;
        content-align: center middle;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("ctrl+s", "save", "Save"),
        Binding("e", "edit", "Edit", priority=True),
        Binding("a", "add", "Add", priority=True),
        Binding("d", "delete", "Delete", priority=True),
        Binding("j", "cursor_down", "Down", show=False, priority=True),
        Binding("k", "cursor_up", "Up", show=False, priority=True),
        Binding("h", "collapse", "Collapse", show=False, priority=True),
        Binding("l", "expand", "Expand", show=False, priority=True),
    ]

    def __init__(self, audio_file: AudioFile, **kwargs) -> None:
        super().__init__(**kwargs)
        self.audio_file = audio_file
        self.meta: AudioMetadata | None = None
        self._selected_key: str | None = None
        self._selected_writable: bool = False
        self._selected_section: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="info-box"):
            yield Static(f"Info — {self.audio_file.path.name}", id="info-title")
            yield Static(str(self.audio_file.path), id="info-subtitle")
            yield Tree("Metadata", id="info-tree")
            with Horizontal(id="edit-row"):
                yield Label("Key:", id="key-label")
                yield Input(placeholder="key", id="key-input")
                yield Label("Value:", id="value-label")
                yield Input(placeholder="value (Enter to save, e to edit)", id="value-input")
                yield Button("Save", id="btn-save", variant="success")
                yield Button("Add", id="btn-add", variant="primary")
                yield Button("Delete", id="btn-del", variant="error")
            yield Static("↳ Tree: j/k navigate • h/l collapse/expand • e/Enter edit • a add • d delete • Ctrl+S save • Esc/q close", id="help")

    def on_mount(self) -> None:
        self._load()

    @work(thread=True)
    def _load(self) -> None:
        meta = read_metadata(self.audio_file)
        self.app.call_from_thread(lambda: self._populate(meta))

    def _populate(self, meta: AudioMetadata) -> None:
        self.meta = meta
        try:
            tree = self.query_one("#info-tree", Tree)
        except Exception:
            return
        tree.clear()
        # update titles
        try:
            self.query_one("#info-title", Static).update(f"Info — {meta.path.name}  ({meta.format_name})")
            self.query_one("#info-subtitle", Static).update(str(meta.path))
        except Exception:
            pass
        sections = _build_tree_data(meta)
        for sec_title, fields in sections:
            sec_node = tree.root.add(sec_title, expand=True)
            sec_node.data = {"section": sec_title}
            for key, label, writable, value in fields:
                display = f"{label}: {value if value else '—'}"
                # mark writable with *
                if writable:
                    display = f"{label}: {value if value else '—'}"
                leaf = sec_node.add_leaf(display, data={"key": key, "label": label, "writable": writable, "value": value, "section": sec_title})
                leaf.data = {"key": key, "label": label, "writable": writable, "value": value, "section": sec_title}
        tree.root.expand()
        # focus tree for vim nav
        try:
            tree.focus()
        except Exception:
            pass

    def _update_selection(self, data: dict | None, focus_edit: bool = False) -> None:
        if not data or "key" not in data:
            return
        self._selected_key = data["key"]
        self._selected_writable = bool(data.get("writable"))
        self._selected_section = data.get("section")
        try:
            self.query_one("#key-input", Input).value = str(data["key"])
            self.query_one("#value-input", Input).value = str(data.get("value", ""))
            self.query_one("#key-input", Input).disabled = not self._selected_writable
            self.query_one("#value-input", Input).disabled = not self._selected_writable
            if focus_edit and self._selected_writable:
                self.query_one("#value-input", Input).focus()
        except Exception:
            pass

    @on(Tree.NodeHighlighted)
    def on_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        data = getattr(event.node, "data", None)
        if not data or "key" not in data:
            return
        # highlight: update inputs but don't steal focus (so vim j/k continues)
        self._update_selection(data, focus_edit=False)

    @on(Tree.NodeSelected)
    def on_node_selected(self, event: Tree.NodeSelected) -> None:
        data = getattr(event.node, "data", None)
        if not data or "key" not in data:
            # section header -> toggle expand
            try:
                n = event.node
                if n.allow_expand:
                    n.toggle()
            except Exception:
                pass
            return
        self._update_selection(data, focus_edit=True)

    # -- editing actions --

    @on(Button.Pressed, "#btn-save")
    def on_save_btn(self) -> None:
        self.action_save()

    @on(Button.Pressed, "#btn-add")
    def on_add_btn(self) -> None:
        self.action_add()

    @on(Button.Pressed, "#btn-del")
    def on_del_btn(self) -> None:
        self.action_delete()

    @on(Input.Submitted, "#value-input")
    def on_value_submit(self, event: Input.Submitted) -> None:
        self.action_save()

    @on(Input.Submitted, "#key-input")
    def on_key_submit(self, event: Input.Submitted) -> None:
        self.query_one("#value-input", Input).focus()

    def action_edit(self) -> None:
        # focus value input if writable
        if self._selected_writable:
            try:
                self.query_one("#value-input", Input).focus()
            except Exception:
                pass

    def action_add(self) -> None:
        try:
            k_in = self.query_one("#key-input", Input)
            v_in = self.query_one("#value-input", Input)
            k = k_in.value.strip().lower()
            v = v_in.value
            if not k:
                self.app.notify("Enter key for new tag", severity="warning")
                k_in.focus()
                return
            if not self.meta:
                return
            self.meta.set_tag(k, v)
            self._save_meta()
        except Exception as e:
            self.app.notify(f"Add failed: {e}", severity="error")

    def action_delete(self) -> None:
        if not self._selected_key or not self._selected_writable:
            self.app.notify("Select an editable tag to delete (j/k then d)", severity="warning")
            return
        if not self.meta:
            return
        k = self._selected_key
        # keep at least not crashing if not exists
        self.meta.remove_tag(k)
        # also clear inputs
        try:
            self.query_one("#value-input", Input).value = ""
        except Exception:
            pass
        self._save_meta()

    def action_save(self) -> None:
        if not self.meta:
            return
        try:
            k_in = self.query_one("#key-input", Input)
            v_in = self.query_one("#value-input", Input)
            k = k_in.value.strip().lower()
            v = v_in.value
            if not k and self._selected_key:
                k = self._selected_key
            if not k:
                self.app.notify("No key selected", severity="warning")
                return
            # if key exists, update; else add
            self.meta.set_tag(k, v)
            self._save_meta()
        except Exception as e:
            self.app.notify(f"Save failed: {e}", severity="error")

    def _save_meta(self) -> None:
        if not self.meta:
            return
        # write to disk
        err = write_metadata(self.meta)
        if err:
            self.app.notify(f"Save error: {err}", severity="error")
            return
        self.app.notify("Saved", severity="success")
        # reload to reflect on-disk state (e.g., normalized keys)
        self._load()

    def _is_typing(self) -> bool:
        try:
            from textual.widgets import Input

            f = self.app.focused
            return isinstance(f, Input)
        except Exception:
            return False

    # vim tree nav (guard when typing)
    def action_cursor_down(self) -> None:
        if self._is_typing():
            return
        try:
            self.query_one("#info-tree", Tree).action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        if self._is_typing():
            return
        try:
            self.query_one("#info-tree", Tree).action_cursor_up()
        except Exception:
            pass

    def action_collapse(self) -> None:
        if self._is_typing():
            return
        try:
            t = self.query_one("#info-tree", Tree)
            n = t.cursor_node
            if n and n.allow_expand and n.is_expanded:
                n.collapse()
            elif n and n.parent:
                t.select_node(n.parent)
        except Exception:
            pass

    def action_expand(self) -> None:
        if self._is_typing():
            return
        try:
            t = self.query_one("#info-tree", Tree)
            n = t.cursor_node
            if n and n.allow_expand and not n.is_expanded:
                n.expand()
            elif n and n.children:
                t.select_node(n.children[0])
        except Exception:
            pass

    def action_edit(self) -> None:
        if self._is_typing():
            return
        # focus value input if writable
        if self._selected_writable:
            try:
                self.query_one("#value-input", Input).focus()
            except Exception:
                pass

    def action_close(self) -> None:
        self.dismiss(None)
