"""lazySound - Terminal UI for managing audio file metadata."""

from __future__ import annotations

import sys
from pathlib import Path

from textual.app import App

from lazysound.config import Config
from lazysound.daw import reaper  # noqa: F401 - registers parser
from lazysound.screens.main import MainScreen


class LazySoundApp(App[None]):
    """Main lazySound application."""

    TITLE = "lazySound"
    SUB_TITLE = "Audio metadata manager"
    CSS = """
    Screen {
        background: $background;
    }
    """

    def __init__(self, start_path: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.start_path = start_path or Config.load().start_directory
        self.config = Config.load()

    def on_mount(self) -> None:
        self.push_screen(MainScreen(start_path=self.start_path))


def main() -> None:
    """Entry point for the lazysound CLI."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="lazysound",
        description="A terminal UI for managing audio file metadata",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        help="Directory to open (default: home directory or configured default)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config file",
    )

    args = parser.parse_args()

    start_path = None
    if args.directory:
        start_path = Path(args.directory).resolve()
        if not start_path.is_dir():
            print(f"Error: Not a directory: {start_path}", file=sys.stderr)
            sys.exit(1)

    app = LazySoundApp(start_path=start_path)
    app.run()


if __name__ == "__main__":
    main()
