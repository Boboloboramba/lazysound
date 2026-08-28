"""User configuration for lazySound."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CONFIG_DIR = Path.home() / ".config" / "lazysound"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"


@dataclass
class Config:
    """Application configuration."""

    # Directories
    default_directory: str = ""

    # Display
    show_hidden_files: bool = False
    show_technical_fields: bool = True
    waveform_width: int = 80
    waveform_height: int = 8

    # Search
    default_search_mode: str = "any"
    case_sensitive_search: bool = False

    # Metadata editing
    confirm_batch_edit: bool = True
    backup_before_write: bool = False

    # Supported formats (extensions without dot)
    enabled_formats: list[str] = field(default_factory=lambda: [
        "flac", "wav", "aiff", "aif", "mp3", "ogg", "opus",
        "m4a", "aac", "wma", "ape", "wv", "tta", "mpc", "alac",
    ])

    # DAW project scanning
    scan_daw_projects: bool = True
    daw_formats: list[str] = field(default_factory=lambda: [
        "rpp", "ptx", "logicx", "ardour", "dawproject",
    ])

    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        """Load config from file, falling back to defaults."""
        path = config_path or DEFAULT_CONFIG_FILE
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self, config_path: Path | None = None) -> None:
        """Save config to file."""
        path = config_path or DEFAULT_CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2, default=str))

    @property
    def start_directory(self) -> Path:
        """Get the starting directory."""
        if self.default_directory:
            p = Path(self.default_directory)
            if p.is_dir():
                return p
        return Path.home()
