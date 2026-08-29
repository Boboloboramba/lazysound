"""Directory scanning and audio file detection."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

AUDIO_EXTENSIONS = frozenset({
    # Lossless
    ".flac", ".wav", ".aiff", ".aif", ".alac", ".ape", ".wv", ".tta",
    # Lossy
    ".mp3", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".mpc",
    # DAW project files
    ".rpp", ".ptx", ".pts", ".logicx", ".ardour", ".dawproject",
})

# Human-readable format names
FORMAT_NAMES: dict[str, str] = {
    ".flac": "FLAC",
    ".wav": "WAV",
    ".aiff": "AIFF",
    ".aif": "AIFF",
    ".alac": "ALAC",
    ".ape": "Monkey's Audio",
    ".wv": "WavPack",
    ".tta": "True Audio",
    ".mp3": "MP3",
    ".ogg": "Ogg",
    ".opus": "Opus",
    ".m4a": "M4A/AAC",
    ".aac": "AAC",
    ".wma": "WMA",
    ".mpc": "Musepack",
    ".rpp": "Reaper Project",
    ".ptx": "Pro Tools",
    ".pts": "Pro Tools Session",
    ".logicx": "Logic Pro",
    ".ardour": "Ardour Session",
    ".dawproject": "DAWproject",
}


@dataclass
class AudioFile:
    """Represents an audio file discovered on disk."""

    path: Path
    size_bytes: int = 0
    format_name: str = ""
    extension: str = ""

    def __post_init__(self) -> None:
        self.size_bytes = self.path.stat().st_size if self.path.exists() else 0
        self.extension = self.path.suffix.lower()
        self.format_name = FORMAT_NAMES.get(self.extension, self.extension.upper())

    @property
    def display_name(self) -> str:
        return self.path.stem

    @property
    def size_display(self) -> str:
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        if self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        if self.size_bytes < 1024 * 1024 * 1024:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"
        return f"{self.size_bytes / (1024 * 1024 * 1024):.2f} GB"

    @property
    def is_daw_project(self) -> bool:
        return self.extension in {".rpp", ".ptx", ".pts", ".logicx", ".ardour", ".dawproject"}


@dataclass
class ScanResult:
    """Result of scanning a directory tree."""

    root: Path
    audio_files: list[AudioFile] = field(default_factory=list)
    daw_projects: list[AudioFile] = field(default_factory=list)
    directories: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _is_html_placeholder(path: Path) -> bool:
    """Detect HTML 404 pages masquerading as audio (e.g., meow.mp3 315 bytes)."""
    try:
        sz = path.stat().st_size
        if sz == 0 or sz > 200_000:
            return False
        # only check small files that could be HTML error pages
        head = path.read_bytes()[:2048].lstrip()
        low = head[:800].lower()
        if low.startswith(b"<!doctype") or low.startswith(b"<html"):
            return True
        if b"<title>404" in low and b"<html" in low:
            return True
        # also check for typical 404 text in small files
        if sz < 2048 and b"not found" in low and b"<html" in low:
            return True
        return False
    except Exception:
        return False


def scan_directory(root: Path, recursive: bool = True, max_depth: int = 10) -> ScanResult:
    """Scan a directory for audio files.

    Args:
        root: Root directory to scan.
        recursive: Whether to recurse into subdirectories.
        max_depth: Maximum recursion depth.

    Returns:
        ScanResult with discovered audio files, DAW projects, and directories.
    """
    result = ScanResult(root=root)

    if not root.exists():
        result.errors.append(f"Directory does not exist: {root}")
        return result

    if not root.is_dir():
        result.errors.append(f"Not a directory: {root}")
        return result

    def _scan(current: Path, depth: int = 0) -> None:
        if depth > max_depth:
            return

        try:
            entries = sorted(current.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            result.errors.append(f"Permission denied: {current}")
            return

        for entry in entries:
            if entry.name.startswith("."):
                continue

            if entry.is_dir():
                result.directories.append(entry)
                if recursive:
                    _scan(entry, depth + 1)
            elif entry.is_file():
                ext = entry.suffix.lower()
                if ext in AUDIO_EXTENSIONS:
                    # Filter out HTML placeholders (e.g., 404 pages saved as .mp3)
                    if _is_html_placeholder(entry):
                        result.errors.append(f"Skipped HTML placeholder: {entry} (not audio)")
                        continue
                    af = AudioFile(path=entry)
                    if af.is_daw_project:
                        result.daw_projects.append(af)
                    else:
                        result.audio_files.append(af)

    _scan(root)
    return result


def get_audio_files_in_directory(directory: Path) -> list[AudioFile]:
    """Get audio files directly in a single directory (non-recursive)."""
    result = scan_directory(directory, recursive=False)
    return result.audio_files
