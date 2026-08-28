"""Search and filter engine for audio files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from lazysound.core.scanner import AudioFile
from lazysound.core.metadata import AudioMetadata


class SearchMode(Enum):
    FILENAME = auto()
    TITLE = auto()
    ARTIST = auto()
    ALBUM = auto()
    GENRE = auto()
    FORMAT = auto()
    ALL_TAGS = auto()
    ANY = auto()


class FilterMode(Enum):
    CONTAINS = auto()
    EXACT = auto()
    STARTS_WITH = auto()
    ENDS_WITH = auto()
    REGEX = auto()
    NOT_CONTAINS = auto()


@dataclass
class SearchQuery:
    """A parsed search query."""

    text: str
    mode: SearchMode = SearchMode.ANY
    filter_mode: FilterMode = FilterMode.CONTAINS
    case_sensitive: bool = False

    @property
    def pattern(self) -> str | None:
        if self.filter_mode == FilterMode.REGEX:
            return self.text
        return None


@dataclass
class SearchResult:
    """A single search result with match context."""

    audio_file: AudioFile
    metadata: AudioMetadata | None = None
    matched_field: str = ""
    matched_value: str = ""

    @property
    def display_name(self) -> str:
        return self.audio_file.path.stem

    @property
    def match_description(self) -> str:
        if self.matched_field:
            return f"{self.matched_field}: {self.matched_value}"
        return "filename"


class SearchEngine:
    """Search and filter audio files by metadata and filename."""

    def __init__(self) -> None:
        self._metadata_cache: dict[Path, AudioMetadata] = {}

    def cache_metadata(self, path: Path, meta: AudioMetadata) -> None:
        """Cache metadata for a file to avoid re-reading during search."""
        self._metadata_cache[path] = meta

    def clear_cache(self) -> None:
        self._metadata_cache.clear()

    def search(
        self,
        files: list[AudioFile],
        query: SearchQuery,
        metadata_map: dict[Path, AudioMetadata] | None = None,
    ) -> list[SearchResult]:
        """Search audio files matching a query.

        Args:
            files: List of AudioFile to search.
            query: The search query.
            metadata_map: Optional pre-loaded metadata for files.

        Returns:
            List of SearchResult sorted by relevance.
        """
        if not query.text.strip():
            return [SearchResult(audio_file=f) for f in files]

        meta_map = metadata_map or self._metadata_cache
        results: list[SearchResult] = []

        for af in files:
            meta = meta_map.get(af.path)
            result = self._match_file(af, meta, query)
            if result:
                results.append(result)

        return results

    def _match_file(
        self,
        af: AudioFile,
        meta: AudioMetadata | None,
        query: SearchQuery,
    ) -> SearchResult | None:
        """Check if a file matches the search query."""
        text = query.text
        if not query.case_sensitive:
            text = text.lower()

        matches: list[tuple[str, str]] = []

        # Filename always checked for ANY mode
        if query.mode in (SearchMode.ANY, SearchMode.FILENAME):
            name = af.path.stem if query.case_sensitive else af.path.stem.lower()
            if self._matches(name, text, query.filter_mode, query.pattern):
                matches.append(("filename", af.path.stem))

        # Check metadata tags if available
        if meta and query.mode != SearchMode.FILENAME:
            tag_checks = self._get_tag_checks(query.mode)
            for tag_key, field_name in tag_checks:
                value = meta.tags.get(tag_key, "")
                if value:
                    cmp_val = value if query.case_sensitive else value.lower()
                    if self._matches(cmp_val, text, query.filter_mode, query.pattern):
                        matches.append((field_name, value))

        # Format check
        if query.mode in (SearchMode.ANY, SearchMode.FORMAT):
            fmt = af.format_name if query.case_sensitive else af.format_name.lower()
            if self._matches(fmt, text, query.filter_mode, query.pattern):
                matches.append(("format", af.format_name))

        if not matches:
            return None

        best = matches[0]
        return SearchResult(
            audio_file=af,
            metadata=meta,
            matched_field=best[0],
            matched_value=best[1],
        )

    def _matches(self, value: str, text: str, mode: FilterMode, pattern: str | None) -> bool:
        if mode == FilterMode.CONTAINS:
            return text in value
        elif mode == FilterMode.EXACT:
            return text == value
        elif mode == FilterMode.STARTS_WITH:
            return value.startswith(text)
        elif mode == FilterMode.ENDS_WITH:
            return value.endswith(text)
        elif mode == FilterMode.NOT_CONTAINS:
            return text not in value
        elif mode == FilterMode.REGEX and pattern:
            try:
                flags = 0 if text != text.lower() else re.IGNORECASE
                return bool(re.search(pattern, value, flags))
            except re.error:
                return False
        return False

    def _get_tag_checks(self, mode: SearchMode) -> list[tuple[str, str]]:
        if mode == SearchMode.TITLE:
            return [("title", "title")]
        elif mode == SearchMode.ARTIST:
            return [("artist", "artist"), ("albumartist", "album artist"), ("performer", "performer")]
        elif mode == SearchMode.ALBUM:
            return [("album", "album")]
        elif mode == SearchMode.GENRE:
            return [("genre", "genre")]
        elif mode == SearchMode.ALL_TAGS:
            return [
                ("title", "title"),
                ("artist", "artist"),
                ("album", "album"),
                ("albumartist", "album artist"),
                ("genre", "genre"),
                ("composer", "composer"),
                ("performer", "performer"),
            ]
        return []


def filter_by_format(files: list[AudioFile], extensions: set[str]) -> list[AudioFile]:
    """Filter files by audio format extensions."""
    return [f for f in files if f.extension.lower() in extensions]


def filter_by_directory(files: list[AudioFile], directory: Path) -> list[AudioFile]:
    """Filter files to those within a specific directory."""
    return [f for f in files if directory in f.path.parents or f.path.parent == directory]
