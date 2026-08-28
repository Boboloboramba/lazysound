"""Search and filter engine — exact + fuzzy with deep metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

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
    FUZZY = auto()  # new: fuzzy matching (default for free-text)


@dataclass
class SearchQuery:
    text: str
    mode: SearchMode = SearchMode.ANY
    filter_mode: FilterMode = FilterMode.FUZZY
    case_sensitive: bool = False
    fuzzy_threshold: int = 60  # 0-100, for FUZZY
    fuzzy_limit: int | None = None  # max results for fuzzy

    @property
    def pattern(self) -> str | None:
        if self.filter_mode == FilterMode.REGEX:
            return self.text
        return None


@dataclass
class SearchResult:
    audio_file: AudioFile
    metadata: AudioMetadata | None = None
    matched_field: str = ""
    matched_value: str = ""
    score: float = 0.0  # 0-100, for fuzzy ranking
    haystack: str = ""  # full searchable text for debugging/highlight

    @property
    def display_name(self) -> str:
        return self.audio_file.path.stem

    @property
    def match_description(self) -> str:
        if self.matched_field:
            return f"{self.matched_field}: {self.matched_value}"
        return "filename"


# -- fuzzy helpers --

def _fuzzy_score(query: str, target: str) -> float:
    """Return 0-100 fuzzy score. Uses rapidfuzz if available, else difflib."""
    if not query or not target:
        return 0.0
    q = query.lower()
    t = target.lower()
    # quick exact/contains bonus
    if q == t:
        return 100.0
    if q in t:
        # strong bonus for substring, but use fuzz for ranking longer strings
        # partial ratio will be ~100 anyway; return 95+ proportional to coverage
        return 90.0 + (len(q) / len(t)) * 10

    try:
        from rapidfuzz import fuzz  # type: ignore

        # WRatio is good overall; partial_ratio handles substrings
        # take best of WRatio and partial
        s1 = fuzz.WRatio(q, t)
        s2 = fuzz.partial_ratio(q, t)
        # token sort helps for out-of-order words
        s3 = fuzz.token_sort_ratio(q, t)
        return max(float(s1), float(s2) * 0.95, float(s3) * 0.9)
    except ImportError:
        import difflib

        return difflib.SequenceMatcher(None, q, t).ratio() * 100


def _haystack_for_file(af: AudioFile, meta: AudioMetadata | None) -> tuple[str, dict[str, str]]:
    """Build searchable haystack string plus field map.

    Returns (haystack, field_map) where field_map is field->value for per-field scoring.
    """
    fields: dict[str, str] = {}
    parts: list[str] = []

    # file system
    fields["filename"] = af.path.stem
    fields["path"] = str(af.path)
    fields["format"] = af.format_name
    fields["extension"] = af.extension
    parts.extend([fields["filename"], fields["format"], fields["path"]])

    if meta:
        # all tag values
        for k, v in meta.tags.items():
            fk = k.lower()
            # mutagen normalizes to lowercase; keep as is
            fields[fk] = v
            parts.append(v)
        # also technical for deep search (bitrate, sample_rate, etc)
        for k, v in meta.technical.items():
            fk = f"tech_{k}"
            fields[fk] = v
            parts.append(v)
        # raw_tags keys also
        for k in meta.raw_tags:
            if k.lower() not in fields:
                fields[k.lower()] = ", ".join(meta.raw_tags[k])

    haystack = " | ".join(p for p in parts if p)
    return haystack, fields


class SearchEngine:
    """Search and filter audio files by filename + deep metadata (tags, technical, path)."""

    def __init__(self) -> None:
        self._metadata_cache: dict[Path, AudioMetadata] = {}
        self._haystack_cache: dict[Path, tuple[str, dict[str, str]]] = {}

    def cache_metadata(self, path: Path, meta: AudioMetadata) -> None:
        self._metadata_cache[path] = meta
        # invalidate haystack
        self._haystack_cache.pop(path, None)

    def clear_cache(self) -> None:
        self._metadata_cache.clear()
        self._haystack_cache.clear()

    def build_index(self, files: list[AudioFile], metadata_map: dict[Path, AudioMetadata] | None = None) -> None:
        """Pre-build haystack cache for fast fuzzy queries (call after metadata indexed)."""
        m = metadata_map or self._metadata_cache
        for af in files:
            meta = m.get(af.path)
            if af.path not in self._haystack_cache:
                self._haystack_cache[af.path] = _haystack_for_file(af, meta)

    # -- exact/filter search (preserved) --

    def search(
        self,
        files: list[AudioFile],
        query: SearchQuery,
        metadata_map: dict[Path, AudioMetadata] | None = None,
    ) -> list[SearchResult]:
        if query.filter_mode == FilterMode.FUZZY:
            return self.fuzzy_search(files, query.text, metadata_map, threshold=query.fuzzy_threshold, limit=query.fuzzy_limit)
        if not query.text.strip():
            return [SearchResult(audio_file=f, metadata=(metadata_map or self._metadata_cache).get(f.path), haystack="") for f in files]
        meta_map = metadata_map or self._metadata_cache
        results: list[SearchResult] = []
        for af in files:
            meta = meta_map.get(af.path)
            r = self._match_file(af, meta, query)
            if r:
                # enrich haystack
                hs, _ = self._haystack_for_cached(af, meta)
                r.haystack = hs
                results.append(r)
        return results

    def _haystack_for_cached(self, af: AudioFile, meta: AudioMetadata | None) -> tuple[str, dict[str, str]]:
        if af.path in self._haystack_cache:
            return self._haystack_cache[af.path]
        hs, fm = _haystack_for_file(af, meta)
        self._haystack_cache[af.path] = (hs, fm)
        return hs, fm

    # -- fuzzy --

    def fuzzy_search(
        self,
        files: list[AudioFile],
        query_text: str,
        metadata_map: dict[Path, AudioMetadata] | None = None,
        threshold: int = 35,
        limit: int | None = None,
    ) -> list[SearchResult]:
        """Fuzzy search across deep metadata. Returns ranked results."""
        q = query_text.strip()
        if not q:
            meta_map = metadata_map or self._metadata_cache
            return [SearchResult(audio_file=f, metadata=meta_map.get(f.path), score=100, haystack="") for f in files]

        q_lower = q.lower()
        meta_map = metadata_map or self._metadata_cache
        scored: list[SearchResult] = []

        for af in files:
            meta = meta_map.get(af.path)
            haystack, field_map = self._haystack_for_cached(af, meta)

            # per-field scoring for better field-aware ranking
            best_score = 0.0
            best_field = "haystack"
            best_value = haystack[:80]

            # score haystack overall
            overall = _fuzzy_score(q_lower, haystack)
            if overall > best_score:
                best_score = overall
                best_field = "any"
                best_value = haystack[:100]

            # per-field scoring to find best matching tag
            for field, val in field_map.items():
                if not val:
                    continue
                # for ANY/filtered: check field; scoring per field often higher for short queries
                s = _fuzzy_score(q_lower, val)
                # boost exact field matches slightly
                if s > best_score:
                    best_score = s
                    best_field = field
                    best_value = val

            # Also try token-wise: if query has multiple words, average?
            # WRatio handles tokens, so no need.

            if best_score >= threshold:
                scored.append(
                    SearchResult(
                        audio_file=af,
                        metadata=meta,
                        matched_field=best_field,
                        matched_value=best_value,
                        score=best_score,
                        haystack=haystack,
                    )
                )

        scored.sort(key=lambda r: r.score, reverse=True)
        if limit:
            scored = scored[:limit]
        return scored

    # -- exact helpers --

    def _match_file(self, af: AudioFile, meta: AudioMetadata | None, query: SearchQuery) -> SearchResult | None:
        text = query.text
        if not query.case_sensitive:
            text = text.lower()
        matches: list[tuple[str, str]] = []
        if query.mode in (SearchMode.ANY, SearchMode.FILENAME):
            name = af.path.stem if query.case_sensitive else af.path.stem.lower()
            if self._matches(name, text, query.filter_mode, query.pattern):
                matches.append(("filename", af.path.stem))
        if meta and query.mode != SearchMode.FILENAME:
            tag_checks = self._get_tag_checks(query.mode)
            # deep: check all tags if ANY
            if query.mode == SearchMode.ANY:
                for k, v in meta.tags.items():
                    if not v:
                        continue
                    cmp_val = v if query.case_sensitive else v.lower()
                    if self._matches(cmp_val, text, query.filter_mode, query.pattern):
                        matches.append((k, v))
                # also check technical fields
                for k, v in meta.technical.items():
                    if not v:
                        continue
                    cmp_val = v if query.case_sensitive else v.lower()
                    if self._matches(cmp_val, text, query.filter_mode, query.pattern):
                        matches.append((f"tech:{k}", v))
            else:
                for tag_key, field_name in tag_checks:
                    value = meta.tags.get(tag_key, "")
                    if value:
                        cmp_val = value if query.case_sensitive else value.lower()
                        if self._matches(cmp_val, text, query.filter_mode, query.pattern):
                            matches.append((field_name, value))
        if query.mode in (SearchMode.ANY, SearchMode.FORMAT):
            fmt = af.format_name if query.case_sensitive else af.format_name.lower()
            if self._matches(fmt, text, query.filter_mode, query.pattern):
                matches.append(("format", af.format_name))
        if not matches:
            return None
        best = matches[0]
        return SearchResult(audio_file=af, metadata=meta, matched_field=best[0], matched_value=best[1], score=100)

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
    return [f for f in files if f.extension.lower() in extensions]


def filter_by_directory(files: list[AudioFile], directory: Path) -> list[AudioFile]:
    return [f for f in files if directory in f.path.parents or f.path.parent == directory]
