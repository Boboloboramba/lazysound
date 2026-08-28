"""DAW integration base class and registry."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DAWProject:
    """Represents a DAW project file."""

    path: Path
    daw_name: str
    format_name: str
    sample_rate: int = 0
    bpm: float = 0.0
    time_sig_num: int = 4
    time_sig_den: int = 4
    key: str = ""
    tracks: list[str] = field(default_factory=list)
    markers: list[tuple[float, str]] = field(default_factory=list)
    regions: list[tuple[float, float, str]] = field(default_factory=list)
    referenced_files: list[Path] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.path.stem

    @property
    def track_count(self) -> int:
        return len(self.tracks)


class DAWParser(abc.ABC):
    """Abstract base class for DAW project parsers."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable DAW name."""

    @property
    @abc.abstractmethod
    def extensions(self) -> list[str]:
        """Supported file extensions (with dot)."""

    @abc.abstractmethod
    def parse(self, path: Path) -> DAWProject | None:
        """Parse a DAW project file.

        Args:
            path: Path to the project file.

        Returns:
            DAWProject if parseable, None otherwise.
        """

    def can_parse(self, path: Path) -> bool:
        """Check if this parser can handle the given file."""
        return path.suffix.lower() in self.extensions


# Registry of available parsers
_parsers: dict[str, DAWParser] = {}


def register_parser(parser: DAWParser) -> None:
    """Register a DAW parser."""
    _parsers[parser.name] = parser


def get_parser(daw_name: str) -> DAWParser | None:
    """Get a registered parser by DAW name."""
    return _parsers.get(daw_name)


def get_parser_for_file(path: Path) -> DAWParser | None:
    """Get the appropriate parser for a file."""
    for parser in _parsers.values():
        if parser.can_parse(path):
            return parser
    return None


def list_parsers() -> list[DAWParser]:
    """List all registered parsers."""
    return list(_parsers.values())


def parse_daw_project(path: Path) -> DAWProject | None:
    """Parse a DAW project file using the appropriate parser."""
    parser = get_parser_for_file(path)
    if parser:
        try:
            return parser.parse(path)
        except Exception:
            return None
    return None
