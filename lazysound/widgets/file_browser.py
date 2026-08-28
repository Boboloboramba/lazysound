"""Directory tree browser widget."""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, Tree


class FileBrowser(Widget):
    """A directory tree browser for navigating to audio files."""

    DEFAULT_CSS = """
    FileBrowser {
        height: 1fr;
        width: 1fr;
        border: solid $primary;
    }
    FileBrowser > Static {
        dock: top;
        padding: 0 1;
        background: $accent;
        color: $text;
        text-style: bold;
    }
    FileBrowser Tree {
        height: 1fr;
    }
    """

    current_path: reactive[Path] = reactive(Path.home())

    def __init__(self, start_path: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        if start_path:
            self.current_path = start_path

    def compose(self) -> ComposeResult:
        yield Static("Directories")
        yield Tree("Home", id="dir-tree")

    def on_mount(self) -> None:
        tree = self.query_one("#dir-tree", Tree)
        self._populate_tree(tree, self.current_path)

    def _populate_tree(self, tree: Tree, path: Path, parent=None) -> None:
        """Populate tree nodes for a directory."""
        node = parent if parent else tree.root
        try:
            dirs = sorted(
                [d for d in path.iterdir() if d.is_dir() and not d.name.startswith(".")],
                key=lambda d: d.name.lower(),
            )
            for d in dirs[:200]:  # Limit for performance
                child = node.add_leaf(d.name, data=d)
                # Pre-add a placeholder so expand arrow shows
                if any(sub.is_dir() for sub in d.iterdir() if not sub.name.startswith(".")):
                    child.add_leaf("Loading...")
        except PermissionError:
            node.add_leaf("Permission denied")

    @on(Tree.NodeExpanded)
    def on_node_expanded(self, event: Tree.NodeExpanded) -> None:
        """Lazy-load directories when expanded."""
        node = event.node
        data = node.data
        if isinstance(data, Path) and data.is_dir():
            # Clear placeholder and populate
            if node.children and node.children[0].allow_expand is False:
                # Check if it's just our placeholder
                first_label = str(node.children[0].label)
                if first_label in ("Loading...", "Permission denied"):
                    node.remove_children()
                    self._populate_tree(self.query_one("#dir-tree", Tree), data, node)

    @on(Tree.NodeSelected)
    def on_node_selected(self, event: Tree.NodeSelected) -> None:
        """Navigate to selected directory."""
        data = event.node.data
        if isinstance(data, Path) and data.is_dir():
            self.current_path = data
            self.post_message(DirectoryChanged(data))

    def watch_current_path(self, path: Path) -> None:
        """Update the tree when path changes."""
        tree = self.query_one("#dir-tree", Tree)
        tree.root.label = str(path.name) or str(path)
        tree.root.data = path
        tree.root.remove_children()
        self._populate_tree(tree, path)


class DirectoryChanged:
    """Message posted when the selected directory changes."""

    def __init__(self, path: Path) -> None:
        self.path = path
