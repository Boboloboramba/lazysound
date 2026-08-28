"""Search bar widget for filtering audio files."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Select, Static

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
    ("Contains", "contains"),
    ("Exact", "exact"),
    ("Starts With", "starts_with"),
    ("Ends With", "ends_with"),
    ("Regex", "regex"),
    ("Not Contains", "not_contains"),
]


class SearchBar(Widget):
    """A search bar with mode selection for filtering audio files."""

    DEFAULT_CSS = """
    SearchBar {
        height: 3;
        dock: top;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $primary;
    }
    SearchBar Input {
        width: 3fr;
    }
    SearchBar Select {
        width: 1fr;
    }
    """

    query_text: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(placeholder="Search files...", id="search-input")
            yield Select(SEARCH_MODES, value="any", id="search-mode", allow_blank=False)
            yield Select(FILTER_MODES, value="contains", id="filter-mode", allow_blank=False)

    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        self.query_text = event.value
        self.post_message(SearchChanged(self.get_query()))

    @on(Select.Changed, "#search-mode")
    def on_mode_changed(self, event: Select.Changed) -> None:
        self.post_message(SearchChanged(self.get_query()))

    @on(Select.Changed, "#filter-mode")
    def on_filter_changed(self, event: Select.Changed) -> None:
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
            "contains": FilterMode.CONTAINS,
            "exact": FilterMode.EXACT,
            "starts_with": FilterMode.STARTS_WITH,
            "ends_with": FilterMode.ENDS_WITH,
            "regex": FilterMode.REGEX,
            "not_contains": FilterMode.NOT_CONTAINS,
        }
        mode_select = self.query_one("#search-mode", Select)
        filter_select = self.query_one("#filter-mode", Select)

        return SearchQuery(
            text=self.query_text,
            mode=mode_map.get(str(mode_select.value), SearchMode.ANY),
            filter_mode=filter_map.get(str(filter_select.value), FilterMode.CONTAINS),
        )

    def clear(self) -> None:
        self.query_one("#search-input", Input).value = ""
        self.query_text = ""


class SearchChanged(Message):
    """Message posted when the search query changes."""

    def __init__(self, query: SearchQuery) -> None:
        super().__init__()
        self.query = query
