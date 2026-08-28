# lazySound

A terminal user interface for managing, searching, previewing, and editing metadata of audio files.

Built for professional DAW users who need a quick helper for managing audio file libraries.

## Features

- **Browse** directory trees of audio files
- **View & edit** metadata tags across all major formats
- **Search & filter** by filename, artist, album, genre, format, and more
- **Batch editing** - apply tag changes to multiple files at once
- **ASCII waveform** preview in the terminal
- **Format info** - bitrate, sample rate, channels, duration, file size

## Supported Formats

| Format | Read/Write | Notes |
|--------|-----------|-------|
| FLAC | R/W | Vorbis Comments |
| MP3 | R/W | ID3v1/v2 |
| M4A/AAC | R/W | MP4 atoms |
| WAV | R/W | RIFF INFO / ID3 |
| AIFF | R/W | AIFF chunks / ID3 |
| Ogg Vorbis | R/W | Vorbis Comments |
| Opus | R/W | Vorbis Comments |
| WavPack | R/W | APEv2 |
| Monkey's Audio | R/W | APEv2 |
| True Audio | R/W | APEv2 |
| Musepack | R/W | APEv2 |

## DAW Project Support

Pluggable architecture for reading DAW project files:

- **Reaper** (`.RPP`) - tracks, markers, regions
- **Pro Tools** (`.ptx`) - planned
- **Logic Pro** (`.logicx`) - planned
- **Ardour** (`.ardour`) - planned
- **DAWproject** (`.dawproject`) - cross-DAW exchange format

## Installation

```bash
# From source — wrapper makes `lazysound` available globally
git clone https://github.com/Boboloboramba/lazysound.git
cd lazysound
python -m venv .venv
.venv/bin/pip install -e .

# Put `lazysound` on your PATH (so you don't need .venv/bin/lazysound)
ln -sf $(pwd)/.venv/bin/lazysound ~/.local/bin/lazysound  # ~/.local/bin is on PATH on Omarchy
# alternative via pipx (if you have it):
# pipx install -e .

# With DAW support
.venv/bin/pip install -e ".[daw]"

# Development
.venv/bin/pip install -e ".[dev]"
```

## Usage

```bash
# Just type `lazysound` — scans your system for all audio folders
# (home + /usr/share/sounds etc, cached in ~/.cache/lazysound/library.json)
# Shows 86+ files from your real library; press L to browse all folders
lazysound

# Open specific directory
lazysound ~/Music/audio
lazysound ./test_audio
lazysound ./real_samples   # 18 real music + voice samples

# Open with config file
lazysound --config ~/.config/lazysound/config.json
```

### Keybindings

| Key | Action |
|-----|--------|
| `q` | Quit |
| `/` | Focus fuzzy search (deep metadata, WRatio) |
| `Ctrl+K` | Fuzzy palette (system-wide) |
| `Esc` | Clear search / close palette |
| `i` | Info — editable tree view for selected file (j/k navigate, e edit, a add, d delete, Ctrl+S save, Esc close) |
| `L` | Library — system-wide folders with audio/DAW files (r rescan, Enter open) |
| `Space` | Play / Pause (selected file, with waveform + progress) |
| `s` | Stop |
| `←` / `→` | Seek -5s / +5s (click waveform to jump) |
| `h` / `l` | Focus left / right pane |
| `j` / `k` | Cursor down / up (live preview) |
| `G` / `Home` / `End` | Bottom / Top |
| `Ctrl+d` / `Ctrl+u` | Page down / up |
| `b` | Batch edit selected files |
| `r` | Refresh |
| `g` | Go to directory |
| `Enter` | Select file / expand directory |

### Navigation

- **Left pane**: Directory tree browser
- **Center pane**: Audio file list with search bar
- **Right pane**: Metadata viewer/editor with waveform preview

## Configuration

Config file at `~/.config/lazysound/config.json`:

```json
{
  "default_directory": "~/Music/audio",
  "show_hidden_files": false,
  "waveform_width": 80,
  "waveform_height": 8,
  "case_sensitive_search": false,
  "confirm_batch_edit": true,
  "enabled_formats": ["flac", "wav", "mp3", "ogg", "opus", "m4a", "aiff"]
}
```

## Project Structure

```
lazysound/
├── lazysound/
│   ├── app.py              # Entry point & Textual App
│   ├── config.py           # User configuration
│   ├── screens/
│   │   └── main.py         # Main screen & batch edit screen
│   ├── widgets/
│   │   ├── file_browser.py  # Directory tree widget
│   │   ├── file_list.py     # Audio file table widget
│   │   ├── metadata_panel.py # Metadata viewer/editor widget
│   │   ├── search.py        # Search bar widget
│   │   └── waveform.py      # ASCII waveform renderer
│   ├── core/
│   │   ├── scanner.py       # Directory scanning & file detection
│   │   ├── metadata.py      # Mutagen wrapper for all formats
│   │   ├── search.py        # Search & filter engine
│   │   └── batch.py         # Batch edit operations
│   └── daw/
│       ├── base.py          # DAW parser base & registry
│       └── reaper.py        # Reaper .RPP parser
└── pyproject.toml
```

## Tech Stack

- **Python 3.11+**
- **[Textual](https://github.com/Textualize/textual)** - TUI framework
- **[Mutagen](https://github.com/quodlibet/mutagen)** - Audio metadata I/O
- **[Librosa](https://github.com/librosa/librosa)** - Audio analysis
- **[Rich](https://github.com/Textualize/rich)** - Terminal formatting

## License

MIT
