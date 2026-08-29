"""Main screen — 3 panes + prominent fuzzy search + palette + bottom playback."""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.reactive import reactive
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Select, Static

from lazysound.core.library import AudioLibrary
from lazysound.core.metadata import read_metadata
from lazysound.core.scanner import AudioFile, scan_directory
from lazysound.core.search import SearchEngine, SearchQuery
from lazysound.widgets.file_browser import DirectoryChanged, FileBrowser
from lazysound.widgets.file_list import FileList, FileSelected
from lazysound.widgets.metadata_panel import MetadataPanel
from lazysound.widgets.playback import PlaybackPanel
from lazysound.widgets.search import SearchBar, SearchChanged


class MainScreen(Screen):
    CSS = """
    MainScreen #main-row {
        height: 1fr;
    }
    #left-pane {
        width: 28;
        min-width: 16;
    }
    #center-pane {
        width: 1fr;
        min-width: 20;
    }
    #right-pane {
        width: 1fr;
        min-width: 24;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("slash", "focus_search", "Search"),
        Binding("ctrl+k", "palette", "Palette"),
        Binding("escape", "clear_search", "Clear"),
        Binding("space", "play_pause", "Play/Pause"),
        Binding("s", "stop", "Stop", key_display="s"),
        Binding("left", "seek_back", " -5s"),
        Binding("right", "seek_forward", " +5s"),
        Binding("b", "batch_edit", "Batch Edit"),
        Binding("r", "refresh", "Refresh"),
        Binding("g", "goto", "Go To"),
        Binding("i", "info", "Info"),
        Binding("I", "info", "Info", show=False),
        Binding("L", "library", "Library"),
        Binding("ctrl+l", "library", "Library", show=False),
        Binding("E", "error_log", "Errors"),
        Binding("ctrl+e", "error_log", "Errors", show=False),
        # vim-style hjkl (priority so they work when DataTable/Tree has focus)
        Binding("j", "cursor_down", "Down", show=False, priority=True),
        Binding("k", "cursor_up", "Up", show=False, priority=True),
        Binding("h", "focus_left", "Left", show=False, priority=True),
        Binding("l", "focus_right", "Right", show=False, priority=True),
        Binding("G", "cursor_bottom", "Bottom", show=False, priority=True),
        Binding("home", "cursor_top", "Top", show=False, priority=True),
        Binding("end", "cursor_bottom", "Bottom", show=False, priority=True),
        Binding("ctrl+d", "page_down", "Page Down", show=False, priority=True),
        Binding("ctrl+u", "page_up", "Page Up", show=False, priority=True),
        Binding("enter", "select_focused", "Select", show=False),
    ]

    current_path: reactive[Path] = reactive(Path.home())
    selected_file: reactive[AudioFile | None] = reactive(None)
    search_engine: SearchEngine = SearchEngine()

    def __init__(self, start_path: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        if start_path:
            self.current_path = start_path
        self.all_files: list[AudioFile] = []
        self._indexed: int = 0
        self.library = AudioLibrary()

    def compose(self) -> ComposeResult:
        yield Header()
        yield SearchBar(id="search-bar")
        with Horizontal(id="main-row"):
            with Vertical(id="left-pane"):
                yield FileBrowser(start_path=self.current_path, id="file-browser")
            with Vertical(id="center-pane"):
                yield FileList(start_path=self.current_path, id="file-list")
            with Vertical(id="right-pane"):
                yield MetadataPanel(id="metadata-panel")
        yield PlaybackPanel(id="playback-panel")
        yield Footer()

    def on_mount(self) -> None:
        self._rebuild_index()
        # vim-friendly: focus file list so hjkl works immediately
        self.set_timer(0.6, lambda: self._focus_file_list())
        # system-wide folder tracking (background)
        self._maybe_system_scan()

    def _focus_file_list(self) -> None:
        try:
            self.query_one("#file-table", DataTable).focus()
        except Exception:
            pass

    # -- directory / index --

    @on(DirectoryChanged)
    def on_directory_changed(self, event: DirectoryChanged) -> None:
        self.current_path = event.path
        self.query_one("#file-list", FileList).current_path = event.path
        self._rebuild_index()

    @work(thread=True)
    def _rebuild_index(self) -> None:
        root = self.current_path
        try:
            res = scan_directory(root, recursive=True, max_depth=6)
            files = res.audio_files
        except Exception:
            files = []
        self.all_files = files
        # cache current file-list's files as fallback? file_list will show nested? keep file_list showing current dir only when not searching
        # deep index metadata
        indexed = 0
        for af in files:
            try:
                meta = read_metadata(af)
                self.search_engine.cache_metadata(af.path, meta)
                indexed += 1
                if indexed % 20 == 0 or indexed == len(files):
                    c = indexed
                    t = len(files)

                    def _upd(c=c, t=t):
                        try:
                            sb = self.query_one("#search-bar", SearchBar)
                            sb.update_index_hint(c, t)
                        except Exception:
                            pass

                    self.app.call_from_thread(_upd)
            except Exception:
                indexed += 1
        self._indexed = indexed
        # final build haystack and hint
        try:
            self.search_engine.build_index(files)
        except Exception:
            pass

        def _done():
            try:
                sb = self.query_one("#search-bar", SearchBar)
                sb.update_index_hint(indexed, len(files))
                q = sb.get_query()
                if q.text.strip():
                    self._apply_search(q)
                else:
                    # show files under current_path (recursive) in file list
                    try:
                        fl = self.query_one("#file-list", FileList)
                        # filter all_files to those under current_path
                        cur = self.current_path
                        shown = [f for f in files if cur in f.path.parents or f.path.parent == cur]
                        if shown:
                            fl.set_files(shown)
                            sb.set_result_count(len(shown), len(files))
                    except Exception:
                        pass
            except Exception:
                pass

        self.app.call_from_thread(_done)

    # -- selection --

    @on(FileSelected)
    def on_file_selected(self, event: FileSelected) -> None:
        self.selected_file = event.audio_file
        try:
            self.query_one("#metadata-panel", MetadataPanel).current_file = event.audio_file
            self.query_one("#playback-panel", PlaybackPanel).current_file = event.audio_file
        except Exception:
            pass

    # -- search --

    @on(SearchChanged)
    def on_search_changed(self, event: SearchChanged) -> None:
        self._apply_search(event.query)

    def _apply_search(self, query: SearchQuery) -> None:
        file_list = self.query_one("#file-list", FileList)
        bar = self.query_one("#search-bar", SearchBar)
        total = len(self.all_files) if self.all_files else len(file_list.files)

        if not query.text.strip():
            # restore recursive view under current_path
            if self.all_files:
                cur = self.current_path
                shown_files = [f for f in self.all_files if cur in f.path.parents or f.path.parent == cur]
                if shown_files:
                    file_list.set_files(shown_files)
                else:
                    file_list._load_files()
            else:
                file_list._load_files()
            shown = len(file_list.files)
            bar.set_result_count(shown, total, self._indexed if self.all_files else None)
            return

        # deep fuzzy search over all_files (falls back to file_list.files if all_files empty)
        pool = self.all_files if self.all_files else file_list.files
        results = self.search_engine.search(pool, query)
        shown = len(results)
        bar.set_result_count(shown, total)

        # render in file_list (show deep results with relative path)
        try:
            table = file_list.query_one("#file-table", DataTable)
        except Exception:
            return
        table.clear()
        # keep file_list.files in sync so selection works
        file_list.files = [r.audio_file for r in results]
        for r in results:
            # show stem + matched field hint + dir
            hint = r.matched_field
            if hint and hint != "filename":
                display = f"{r.audio_file.path.stem}  [{hint}:{r.matched_value[:24]}]"
            else:
                display = r.audio_file.path.stem
            # truncate display
            if len(display) > 38:
                display = display[:36] + "…"
            # score badge for fuzzy
            score_str = f"{int(r.score)}" if r.score else ""
            table.add_row(display, r.audio_file.format_name, r.audio_file.size_display)

    # -- actions --

    def action_focus_search(self) -> None:
        self.query_one("#search-bar", SearchBar).focus_input()

    def action_palette(self) -> None:
        pool = self.all_files if self.all_files else self.query_one("#file-list", FileList).files
        cache = dict(self.search_engine._metadata_cache)
        self.app.push_screen(FuzzyPalette(pool, cache, self.search_engine), self._on_palette_pick)

    def _on_palette_pick(self, picked: AudioFile | None) -> None:
        if not picked:
            return
        # switch to its directory and select it
        try:
            # update file list to show deep results: temporarily set all_files filter? Simpler: navigate to directory
            target_dir = picked.path.parent
            self.current_path = target_dir
            # update file Browser + file list
            try:
                from lazysound.widgets.file_browser import FileBrowser

                self.query_one(FileBrowser).current_path = target_dir
            except Exception:
                pass
            fl = self.query_one("#file-list", FileList)
            fl.current_path = target_dir
            # defer selection until file_list loaded
            def _select():
                # ensure file is in list
                for idx, af in enumerate(fl.files):
                    if af.path == picked.path:
                        try:
                            tbl = fl.query_one("#file-table", DataTable)
                            tbl.move_cursor(row=idx)
                            # trigger selection
                            fl.post_message(FileSelected(af))
                        except Exception:
                            pass
                        break

            self.set_timer(0.15, _select)
        except Exception:
            pass

    def action_clear_search(self) -> None:
        bar = self.query_one("#search-bar", SearchBar)
        if bar.query_text:
            bar.clear()
            # will trigger SearchChanged -> _apply_search restores list
        else:
            # if already empty and focus is in search, blur
            try:
                self.query_one("#file-list", FileList).focus()
            except Exception:
                pass

    def action_refresh(self) -> None:
        self.query_one("#file-list", FileList)._load_files()
        self._rebuild_index()

    def action_goto(self) -> None:
        self.app.push_screen(GotoScreen(self.current_path))

    def action_batch_edit(self) -> None:
        file_list = self.query_one("#file-list", FileList)
        if file_list.files:
            self.app.push_screen(BatchEditScreen(file_list.files))

    def action_info(self) -> None:
        # don't trigger when typing
        if self._is_input_focused():
            return
        target = self.selected_file
        if not target:
            # try to get from file list
            try:
                fl = self.query_one("#file-list", FileList)
                target = fl.get_selected_file()
            except Exception:
                target = None
        if not target:
            self.app.notify("No file selected — use j/k to highlight a file then press i", severity="warning")
            return
        from lazysound.screens.info import MetadataInfoScreen

        self.app.push_screen(MetadataInfoScreen(target))

    def action_library(self) -> None:
        if self._is_input_focused():
            return
        from lazysound.screens.library import LibraryScreen

        self.app.push_screen(LibraryScreen(self.library), self._on_library_pick)

    def _on_library_pick(self, picked: Path | None) -> None:
        if not picked or not picked.is_dir():
            return
        self.current_path = picked
        try:
            from lazysound.widgets.file_browser import FileBrowser

            self.query_one(FileBrowser).current_path = picked
        except Exception:
            pass
        try:
            self.query_one("#file-list", FileList).current_path = picked
        except Exception:
            pass
        self._rebuild_index()

    def action_error_log(self) -> None:
        if self._is_input_focused():
            return
        from lazysound.screens.errors import ErrorLogScreen

        self.app.push_screen(ErrorLogScreen(), self._on_error_log_pick)

    def _on_error_log_pick(self, picked: Path | None) -> None:
        if not picked or not picked.is_dir():
            return
        self.current_path = picked
        try:
            from lazysound.widgets.file_browser import FileBrowser

            self.query_one(FileBrowser).current_path = picked
        except Exception:
            pass
        try:
            self.query_one("#file-list", FileList).current_path = picked
        except Exception:
            pass
        self._rebuild_index()

    def _maybe_system_scan(self) -> None:
        # run in background if stale or empty
        if self.library.is_stale(max_age_hours=24):
            self.app.notify("Scanning system for audio folders… (L to view library)", severity="information", timeout=8)
            self._system_scan_bg()
        else:
            # still notify count
            try:
                cnt = len(self.library.get_folders())
                if cnt:
                    self.app.notify(f"Library: {cnt} folders with audio/DAW files (L to view, E for errors)", severity="information", timeout=8)
            except Exception:
                pass

    @work(thread=True)
    def _system_scan_bg(self) -> None:
        def _prog(scanned: int, found: int, cur: str) -> None:
            if scanned % 600 == 0:
                try:
                    self.app.call_from_thread(lambda: self.app.notify(f"Library scan: {scanned} dirs, {found} folders — {cur}", severity="information", timeout=2))
                except Exception:
                    pass

        try:
            folders = self.library.scan_system(progress_cb=_prog)
            self.app.call_from_thread(lambda: self.app.notify(f"Library scan done — {len(folders)} folders tracked (L to view)", severity="success"))
        except Exception as e:
            self.app.call_from_thread(lambda: self.app.notify(f"Library scan error: {e}", severity="error"))

    def action_play_pause(self) -> None:
        # don't steal space when typing in search/input
        try:
            focused = self.app.focused
            if focused and isinstance(focused, Input):
                # let Input handle space
                return
        except Exception:
            pass
        self.query_one("#playback-panel", PlaybackPanel).action_play_pause()

    def action_stop(self) -> None:
        self.query_one("#playback-panel", PlaybackPanel).action_stop()

    def action_seek_back(self) -> None:
        self.query_one("#playback-panel", PlaybackPanel).action_seek_back()

    def action_seek_forward(self) -> None:
        self.query_one("#playback-panel", PlaybackPanel).action_seek_forward()

    # -- vim-style hjkl --

    def _is_input_focused(self) -> bool:
        try:
            f = self.app.focused
            return isinstance(f, (Input, Select))
        except Exception:
            return False

    def _focused_table_or_tree(self):
        try:
            f = self.app.focused
            # walk up to find DataTable / Tree
            if f is None:
                return None
            # direct hit
            from textual.widgets import DataTable, Tree

            if isinstance(f, (DataTable, Tree)):
                return f
            # check if focused is inside FileList/FileBrowser and return inner table/tree
            # fallback: find the widget that contains focus
            return None
        except Exception:
            return None

    def action_cursor_down(self) -> None:
        if self._is_input_focused():
            return
        # try to move focused DataTable/Tree, else default to file list
        try:
            from textual.widgets import DataTable, Tree

            f = self.app.focused
            if isinstance(f, DataTable):
                f.action_cursor_down()
                return
            if isinstance(f, Tree):
                f.action_cursor_down()
                return
            # no table focused → focus file list and move
            tbl = self.query_one("#file-table", DataTable)
            tbl.focus()
            tbl.action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        if self._is_input_focused():
            return
        try:
            from textual.widgets import DataTable, Tree

            f = self.app.focused
            if isinstance(f, DataTable):
                f.action_cursor_up()
                return
            if isinstance(f, Tree):
                f.action_cursor_up()
                return
            tbl = self.query_one("#file-table", DataTable)
            tbl.focus()
            tbl.action_cursor_up()
        except Exception:
            pass

    def action_focus_left(self) -> None:
        if self._is_input_focused():
            return
        # Vim h in directories panel = go to parent (like `cd ..`)
        try:
            from textual.widgets import DataTable, Tree

            f = self.app.focused
            if isinstance(f, Tree) and f.id == "dir-tree":
                fb = self.query_one(FileBrowser)
                parent = fb.current_path.parent
                if parent != fb.current_path and str(parent) != str(fb.current_path):
                    try:
                        if parent.exists() or str(parent) == "/":
                            fb.current_path = parent
                            self.current_path = parent
                            try:
                                self.query_one(FileList).current_path = parent
                            except Exception:
                                pass
                            self._rebuild_index()
                            return
                    except Exception:
                        pass
                # at top or can't go parent -> fall through to pane switch
            order = []
            try:
                order.append(self.query_one("#dir-tree", Tree))
            except Exception:
                pass
            try:
                order.append(self.query_one("#file-table", DataTable))
            except Exception:
                pass
            if not order:
                return
            idx = -1
            for i, w in enumerate(order):
                if w.has_focus:
                    idx = i
                    break
            if idx == -1:
                order[0].focus()
            elif idx > 0:
                order[idx - 1].focus()
            else:
                order[-1].focus()
        except Exception:
            pass

    def action_focus_right(self) -> None:
        if self._is_input_focused():
            return
        try:
            from textual.widgets import DataTable, Tree

            f = self.app.focused
            if isinstance(f, Tree) and f.id == "dir-tree":
                tree = f
                node = tree.cursor_node
                data = getattr(node, "data", None) if node else None
                fb = self.query_one(FileBrowser)
                if isinstance(data, Path) and data.is_dir() and data != fb.current_path:
                    fb.current_path = data
                    self.current_path = data
                    try:
                        self.query_one(FileList).current_path = data
                    except Exception:
                        pass
                    self._rebuild_index()
                    return
                # otherwise (at root or no child) fall through to pane switch
            order = []
            try:
                order.append(self.query_one("#dir-tree", Tree))
            except Exception:
                pass
            try:
                order.append(self.query_one("#file-table", DataTable))
            except Exception:
                pass
            if not order:
                return
            idx = -1
            for i, w in enumerate(order):
                if w.has_focus:
                    idx = i
                    break
            if idx == -1:
                order[-1].focus()
            elif idx < len(order) - 1:
                order[idx + 1].focus()
            else:
                order[0].focus()
        except Exception:
            pass

    def action_cursor_top(self) -> None:
        if self._is_input_focused():
            return
        try:
            from textual.widgets import DataTable, Tree

            f = self.app.focused
            if isinstance(f, DataTable):
                f.move_cursor(row=0)
                return
            if isinstance(f, Tree):
                f.select_node(f.root)
                return
            tbl = self.query_one("#file-table", DataTable)
            tbl.move_cursor(row=0)
            tbl.focus()
        except Exception:
            pass

    def action_cursor_bottom(self) -> None:
        if self._is_input_focused():
            return
        try:
            from textual.widgets import DataTable, Tree

            f = self.app.focused
            if isinstance(f, DataTable):
                # move to last row
                last = max(0, f.row_count - 1)
                f.move_cursor(row=last)
                return
            if isinstance(f, Tree):
                # no direct bottom, select last visible leaf
                try:
                    # try to select last child of root
                    if f.root.children:
                        f.select_node(f.root.children[-1])
                except Exception:
                    pass
                return
            tbl = self.query_one("#file-table", DataTable)
            last = max(0, tbl.row_count - 1)
            tbl.move_cursor(row=last)
            tbl.focus()
        except Exception:
            pass

    def action_page_down(self) -> None:
        if self._is_input_focused():
            return
        try:
            from textual.widgets import DataTable, Tree

            f = self.app.focused
            # page = 10 rows
            if isinstance(f, DataTable):
                cur = f.cursor_row or 0
                nxt = min(f.row_count - 1, cur + 10)
                f.move_cursor(row=nxt)
                return
            if isinstance(f, Tree):
                f.action_page_down()
                return
            tbl = self.query_one("#file-table", DataTable)
            cur = tbl.cursor_row or 0
            nxt = min(tbl.row_count - 1, cur + 10)
            tbl.move_cursor(row=nxt)
            tbl.focus()
        except Exception:
            pass

    def action_page_up(self) -> None:
        if self._is_input_focused():
            return
        try:
            from textual.widgets import DataTable, Tree

            f = self.app.focused
            if isinstance(f, DataTable):
                cur = f.cursor_row or 0
                nxt = max(0, cur - 10)
                f.move_cursor(row=nxt)
                return
            if isinstance(f, Tree):
                f.action_page_up()
                return
            tbl = self.query_one("#file-table", DataTable)
            cur = tbl.cursor_row or 0
            nxt = max(0, cur - 10)
            tbl.move_cursor(row=nxt)
            tbl.focus()
        except Exception:
            pass

    def action_select_focused(self) -> None:
        if self._is_input_focused():
            return
        # Enter selects highlighted row (already handled by RowHighlighted, but ensure playback)
        try:
            from textual.widgets import DataTable

            f = self.app.focused
            if isinstance(f, DataTable):
                # trigger select = post FileSelected already via highlight, but ensure play?
                pass
        except Exception:
            pass


class FuzzyPalette(ModalScreen):
    """Full-screen fuzzy palette (like Ctrl+P) with deep metadata ranking."""

    DEFAULT_CSS = """
    FuzzyPalette {
        align: center middle;
        background: rgba(0,0,0,0.6);
    }
    FuzzyPalette #palette-box {
        width: 80;
        height: 28;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 1;
    }
    FuzzyPalette Input {
        dock: top;
        margin-bottom: 1;
    }
    FuzzyPalette DataTable {
        height: 1fr;
    }
    FuzzyPalette #palette-hint {
        height: 1;
        color: $text-muted;
        text-style: italic;
    }
    """

    def __init__(self, files: list[AudioFile], cache: dict, engine: SearchEngine, **kwargs) -> None:
        super().__init__(**kwargs)
        self.files = files
        self.cache = cache
        self.engine = engine
        self._results: list = []

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-box"):
            yield Static("🔍 Fuzzy Palette — deep search (Enter to open, Esc to close)", id="palette-hint")
            yield Input(placeholder="Type to fuzzy-filter by filename / title / artist / album / genre / path …", id="palette-input")
            yield DataTable(id="palette-table")

    def on_mount(self) -> None:
        table = self.query_one("#palette-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Score", "File", "Match", "Format", "Path")
        self.query_one("#palette-input", Input).focus()
        self._update_table("")

    @on(Input.Changed, "#palette-input")
    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_table(event.value)

    def _update_table(self, text: str) -> None:
        from lazysound.core.search import SearchQuery, FilterMode, SearchMode

        table = self.query_one("#palette-table", DataTable)
        table.clear()
        q = SearchQuery(text=text, mode=SearchMode.ANY, filter_mode=FilterMode.FUZZY)
        if text.strip():
            results = self.engine.fuzzy_search(self.files, text, self.cache, threshold=45, limit=100)
        else:
            # show top 50 files as browse
            from lazysound.core.search import SearchResult

            results = [SearchResult(audio_file=f, score=100) for f in self.files[:50]]
        self._results = results
        for r in results:
            score = f"{int(r.score)}" if r.score else ""
            name = r.audio_file.path.stem
            match = f"{r.matched_field}:{r.matched_value[:30]}" if r.matched_field else ""
            fmt = r.audio_file.format_name
            # relative-ish path
            try:
                rel = r.audio_file.path.relative_to(Path.cwd())
            except Exception:
                rel = r.audio_file.path
            table.add_row(score, name, match, fmt, str(rel))

    @on(DataTable.RowSelected, "#palette-table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if idx is not None and 0 <= idx < len(self._results):
            self.dismiss(self._results[idx].audio_file)

    def on_key(self, event) -> None:
        # Textual key handler
        if event.key == "escape":
            self.dismiss(None)


class GotoScreen(Screen):
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
        inp = self.query_one("#path-input", Input)
        path = Path(inp.value)
        if path.is_dir():
            self.dismiss(path)
        else:
            self.app.notify(f"Not a directory: {inp.value}", severity="error")

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)


class BatchEditScreen(Screen):
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
        # keep search index in sync (e.g., Album Artist -> Bob should be found via Artist search)
        try:
            from lazysound.core.metadata import read_metadata as _rm

            main = None
            for s in self.app.screen_stack:
                if s.__class__.__name__ == "MainScreen":
                    main = s
                    break
            if main is not None and hasattr(main, "search_engine"):
                for af in self.files:
                    try:
                        fresh = _rm(af)
                        main.search_engine.cache_metadata(af.path, fresh)
                        try:
                            main.search_engine._haystack_cache.pop(af.path, None)
                        except Exception:
                            pass
                    except Exception:
                        pass
        except Exception:
            pass
        self.app.notify(f"Batch edit: {result.summary}", severity="success" if result.error_count == 0 else "warning")
        self.dismiss(True)

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)
