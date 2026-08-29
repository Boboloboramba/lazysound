"""System-wide audio folder tracking."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from lazysound.core.scanner import AUDIO_EXTENSIONS, FORMAT_NAMES

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "lazysound"
DEFAULT_CACHE_FILE = DEFAULT_CACHE_DIR / "library.json"

# Directories to never descend into
EXCLUDE_DIR_NAMES = frozenset({
    ".git", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "__pycache__", "node_modules", ".cache", ".local", ".cargo", ".rustup",
    ".npm", ".nvm", ".snap", "snap", "__pycache__",
})

# Path prefixes to skip entirely (system pseudo-FS, trash, etc.)
EXCLUDE_PREFIXES = (
    "/proc", "/sys", "/dev", "/run", "/var/tmp",
    "/snap",
)

# Also skip hidden dirs under home that are not music related, but keep scanning complexity low
# We allow hidden = False; we skip any component starting with "." unless it's a known music hidden? No.


def _is_html_placeholder(path: Path) -> bool:
    try:
        sz = path.stat().st_size
        if sz == 0 or sz > 200_000:
            return False
        head = path.read_bytes()[:2048].lstrip()
        low = head[:800].lower()
        if low.startswith(b"<!doctype") or low.startswith(b"<html"):
            return True
        if b"<title>404" in low and b"<html" in low:
            return True
        if sz < 2048 and b"not found" in low and b"<html" in low:
            return True
        return False
    except Exception:
        return False


def _should_skip_dir(path: Path) -> bool:
    name = path.name
    if name.startswith("."):
        return True
    if name in EXCLUDE_DIR_NAMES:
        return True
    s = str(path)
    for pref in EXCLUDE_PREFIXES:
        if s == pref or s.startswith(pref + "/"):
            return True
    return False


@dataclass
class FolderEntry:
    """A folder that contains audio/DAW files."""

    path: str  # store as string for JSON
    audio_count: int = 0
    daw_count: int = 0
    total_bytes: int = 0
    formats: list[str] = field(default_factory=list)  # sorted unique format names
    sample_files: list[str] = field(default_factory=list)  # up to 3 relative paths
    last_scanned: float = 0.0  # epoch

    @property
    def total_count(self) -> int:
        return self.audio_count + self.daw_count

    @property
    def path_obj(self) -> Path:
        return Path(self.path)

    def pretty_size(self) -> str:
        b = self.total_bytes
        if b < 1024:
            return f"{b} B"
        if b < 1024 * 1024:
            return f"{b/1024:.1f} KB"
        if b < 1024 * 1024 * 1024:
            return f"{b/(1024*1024):.1f} MB"
        return f"{b/(1024*1024*1024):.2f} GB"


@dataclass
class LibraryState:
    folders: list[FolderEntry] = field(default_factory=list)
    last_full_scan: float = 0.0
    scan_roots: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class AudioLibrary:
    """Tracks folders system-wide that contain sound/music/DAW files."""

    def __init__(self, cache_file: Path | None = None) -> None:
        self.cache_file = cache_file or DEFAULT_CACHE_FILE
        self.state = LibraryState()
        self._load()

    # -- persistence --

    def _load(self) -> None:
        if not self.cache_file.exists():
            return
        try:
            data = json.loads(self.cache_file.read_text())
            self.state.folders = [FolderEntry(**f) for f in data.get("folders", [])]
            self.state.last_full_scan = data.get("last_full_scan", 0.0)
            self.state.scan_roots = data.get("scan_roots", [])
            self.state.errors = data.get("errors", [])
        except Exception:
            # corrupted cache -> reset
            self.state = LibraryState()

    def save(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "folders": [asdict(f) for f in self.state.folders],
                "last_full_scan": self.state.last_full_scan,
                "scan_roots": self.state.scan_roots,
                "errors": self.state.errors[-20:],
            }
            self.cache_file.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    # -- scan --

    def get_default_roots(self) -> list[Path]:
        """Common locations where audio/DAW projects live."""
        roots: list[Path] = []
        home = Path.home()
        # Primary: home directory (covers ~/Music, ~/Audio, ~/Documents, etc.)
        roots.append(home)
        # System sound locations
        for p in [Path("/usr/share/sounds"), Path("/usr/share/music"), Path("/opt")]:
            if p.is_dir():
                roots.append(p)
        # Removable media
        for p in [Path("/media"), Path("/mnt")]:
            if p.is_dir():
                # don't scan empty /media if no mounts
                try:
                    if any(p.iterdir()):
                        roots.append(p)
                except Exception:
                    pass
        # XDG music dir
        xdg_music = home / "Music"
        if xdg_music.is_dir() and xdg_music not in roots:
            roots.append(xdg_music)
        # Also scan /home for multi-user systems (if we have permission)
        if Path("/home").is_dir() and home != Path("/home"):
            # we already scan home, but scanning /home covers other users' media
            pass
        return roots

    def scan_system(
        self,
        roots: list[Path] | None = None,
        max_depth: int = 8,
        max_folders: int = 5000,
        progress_cb: Callable[[int, int, str], None] | None = None,
        force: bool = False,
    ) -> list[FolderEntry]:
        """Walk roots and find folders directly containing audio files.

        Args:
            roots: Roots to scan. Defaults to get_default_roots().
            max_depth: Max depth relative to each root.
            max_folders: Hard limit to avoid runaway.
            progress_cb: Called as (scanned_dirs, found_folders, current_path).
            force: Ignore cache age.

        Returns:
            List of FolderEntry sorted by path.
        """
        if roots is None:
            roots = self.get_default_roots()
        # deduplicate and filter non-existent
        roots = [r.resolve() for r in roots if r.exists() and r.is_dir()]
        # avoid scanning same subtree twice (e.g., home is subset of /home)
        # simple: keep only roots not contained in another root
        filtered: list[Path] = []
        for r in sorted(roots, key=lambda p: len(str(p))):
            if not any(str(r).startswith(str(o) + "/") for o in filtered):
                filtered.append(r)
        roots = filtered

        folders: dict[str, FolderEntry] = {}
        scanned_dirs = 0
        errors: list[str] = []

        for root in roots:
            # estimate root depth
            root_depth = len(root.parts)
            try:
                for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
                    scanned_dirs += 1
                    cur = Path(dirpath)
                    # prune depth
                    depth = len(cur.parts) - root_depth
                    if depth > max_depth:
                        dirnames[:] = []
                        continue
                    # prune excluded dirnames in-place (so walk doesn't descend)
                    # copy to avoid modification during iteration issues
                    orig = list(dirnames)
                    dirnames[:] = [d for d in orig if not _should_skip_dir(cur / d)]
                    # also skip if current dir itself should be skipped (except root)
                    if cur != root and _should_skip_dir(cur):
                        dirnames[:] = []
                        continue
                    if progress_cb and scanned_dirs % 200 == 0:
                        try:
                            progress_cb(scanned_dirs, len(folders), str(cur))
                        except Exception:
                            pass

                    if len(folders) >= max_folders:
                        break

                    # Count audio files directly in this dir
                    audio_cnt = 0
                    daw_cnt = 0
                    total_bytes = 0
                    formats: set[str] = set()
                    samples: list[str] = []
                    for fn in filenames:
                        if fn.startswith("."):
                            continue
                        ext = Path(fn).suffix.lower()
                        if ext in AUDIO_EXTENSIONS:
                            full = cur / fn
                            # Skip HTML 404 pages masquerading as audio
                            if _is_html_placeholder(full):
                                continue
                            is_daw = ext in {".rpp", ".ptx", ".pts", ".logicx", ".ardour", ".dawproject"}
                            try:
                                sz = full.stat().st_size
                            except Exception:
                                sz = 0
                            total_bytes += sz
                            fmt = FORMAT_NAMES.get(ext, ext.upper())
                            formats.add(fmt)
                            if is_daw:
                                daw_cnt += 1
                            else:
                                audio_cnt += 1
                            if len(samples) < 3:
                                samples.append(fn)

                    if audio_cnt or daw_cnt:
                        entry = FolderEntry(
                            path=str(cur),
                            audio_count=audio_cnt,
                            daw_count=daw_cnt,
                            total_bytes=total_bytes,
                            formats=sorted(formats),
                            sample_files=samples,
                            last_scanned=time.time(),
                        )
                        folders[str(cur)] = entry

                    if scanned_dirs % 500 == 0 and progress_cb:
                        try:
                            progress_cb(scanned_dirs, len(folders), str(cur))
                        except Exception:
                            pass
            except Exception as e:
                errors.append(f"{root}: {e}")

        result = sorted(folders.values(), key=lambda f: f.path.lower())
        self.state.folders = result
        self.state.last_full_scan = time.time()
        self.state.scan_roots = [str(r) for r in roots]
        self.state.errors = errors[-20:]
        self.save()
        if progress_cb:
            try:
                progress_cb(scanned_dirs, len(result), "done")
            except Exception:
                pass
        return result

    def get_folders(self) -> list[FolderEntry]:
        return list(self.state.folders)

    def find_folder(self, path: Path) -> FolderEntry | None:
        s = str(path.resolve())
        for f in self.state.folders:
            if f.path == s:
                return f
        return None

    def is_stale(self, max_age_hours: float = 24) -> bool:
        if not self.state.folders:
            return True
        age = time.time() - self.state.last_full_scan
        return age > max_age_hours * 3600
