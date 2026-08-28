"""Prominent fuzzy search bar + palette for deep metadata search."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Select, Static, Label

from lazysound.core.search import SearchMode, SearchQuery, FilterMode


SEARCH_MODES = [
    ("Any", "any"),
    ("Filename", "filename"),
    ("Title", "title"),
    ("Artist", "artist"),
    ("Album", "album"),
    ("Genre", "genre"),
    ("Format", "format"),
    ("All Tags", "all_tags"),
]

FILTER_MODES = [
    ("Fuzzy", "fuzzy"),
    ("Contains", "contains"),
    ("Exact", "exact"),
    ("Starts With", "starts_with"),
    ("Ends With", "ends_with"),
    ("Regex", "regex"),
    ("Not Contains", "not_contains"),
]


class SearchBar(Widget):
    """Front-and-center fuzzy finder bar with deep metadata indexing."""

    DEFAULT_CSS = """
    SearchBar {
        height: 5;
        dock: top;
        background: $surface;
        border: thick $primary;
        padding: 0 1;
    }
    SearchBar #search-row {
        height: 3;
        width: 1fr;
        align: center middle;
    }
    SearchBar #search-input {
        width: 1fr;
        height: 3;
        border: tall $accent;
    }
    SearchBar #search-input:focus {
        border: tall $success;
    }
    SearchBar Select {
        width: 16;
        height: 3;
        margin-left: 1;
    }
    SearchBar #hint-row {
        height: 1;
        width: 1fr;
        color: $text-muted;
        text-style: italic;
    }
    SearchBar #result-count {
        width: auto;
        min-width: 18;
        content-align: right middle;
        color: $success;
        text-style: bold;
        padding-left: 1;
    }
    """

    query_text: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="search-row"):
                yield Input(
                    placeholder="🔍 Fuzzy search — filename • title • artist • album • genre • path • format (deep metadata, press / to focus, Ctrl+K palette)",
                    id="search-input",
                )
                yield Select(FILTER_MODES, value="fuzzy", id="filter-mode", allow_blank=False)
                yield Select(SEARCH_MODES, value="any", id="search-mode", allow_blank=False)
                yield Label("", id="result-count")
            yield Static("↳ Deep fuzzy • WRatio + partial • / to focus • Ctrl+K palette • Esc clear", id="hint-row")

    def on_mount(self) -> None:
        self._update_hint_indexed(0, 0)

    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        if not self.is_mounted:
            return
        self.query_text = event.value
        self.post_message(SearchChanged(self.get_query()))

    @on(Select.Changed, "#filter-mode")
    def on_filter_changed(self, event: Select.Changed) -> None:
        if not self.is_mounted:
            return
        self.post_message(SearchChanged(self.get_query()))

    @on(Select.Changed, "#search-mode")
    def on_mode_changed(self, event: Select.Changed) -> None:
        if not self.is_mounted:
            return
        self.post_message(SearchChanged(self.get_query()))

    def get_query(self) -> SearchQuery:
        mode_map = {
            "any": SearchMode.ANY,
            "filename": SearchMode.FILENAME,
            "title": SearchMode.TITLE,
            "artist": SearchMode.ARTIST,
            "album": SearchMode.ALBUM,
            "genre": SearchMode.GENRE,
            "format": SearchMode.FORMAT,
            "all_tags": SearchMode.ALL_TAGS,
        }
        filter_map = {
            "fuzzy": FilterMode.FUZZY,
            "contains": FilterMode.CONTAINS,
            "exact": FilterMode.EXACT,
            "starts_with": FilterMode.STARTS_WITH,
            "ends_with": FilterMode.ENDS_WITH,
            "regex": FilterMode.REGEX,
            "not_contains": FilterMode.NOT_CONTAINS,
        }
        try:
            mode_val = str(self.query_one("#search-mode", Select).value)
        except Exception:
            mode_val = "any"
        try:
            filter_val = str(self.query_one("#filter-mode", Select).value)
        except Exception:
            filter_val = "fuzzy"

        return SearchQuery(
            text=self.query_text,
            mode=mode_map.get(mode_val, SearchMode.ANY),
            filter_mode=filter_map.get(filter_val, FilterMode.FUZZY),
        )

    def clear(self) -> None:
        try:
            self.query_one("#search-input", Input).value = ""
        except Exception:
            pass
        self.query_text = ""

    def focus_input(self) -> None:
        try:
            self.query_one("#search-input", Input).focus()
        except Exception:
            pass

    def set_result_count(self, shown: int, total: int, indexed: int | None = None) -> None:
        try:
            label = self.query_one("#result-count", Label)
            if indexed is not None:
                label.update(f"{shown}/{total} • {indexed} indexed")
            else:
                label.update(f"{shown}/{total}")
        except Exception:
            pass

    def _update_hint_indexed(self, indexed: int, total: int) -> None:
        try:
            hint = self.query_one("#hint-row", Static)
            if total > 0:
                hint.update(f"↳ Indexed {indexed}/{total} • Fuzzy WRatio+partial • / focus • Ctrl+K palette • Esc clear")
        except Exception:
            pass

    def update_index_hint(self, indexed: int, total: int) -> None:
        self._update_hint_indexed(indexed, total)
        self.set_result_count(total, total, indexed)


class SearchChanged(Message):
    def __init__(self, query: SearchQuery) -> None:
        super().__init__()
        self.query = query
