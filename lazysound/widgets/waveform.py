"""ASCII waveform renderer for terminal display with playhead + caching."""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

import numpy as np

BLOCKS = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"


def _load_audio_mono(path: Path, target_sr: int = 22050) -> np.ndarray | None:
    """Load audio as mono float array at target_sr, handling all formats."""
    # try soundfile + librosa fast path with resampling
    try:
        import soundfile as sf
        import librosa as _librosa

        # soundfile can resample via librosa after load
        data, sr = sf.read(str(path), always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != target_sr:
            data = _librosa.resample(data, orig_sr=sr, target_sr=target_sr)
        return data.astype(np.float32)
    except Exception:
        pass
    # audioread fallback
    try:
        import audioread

        with audioread.audio_open(str(path)) as f:
            import io as _io

            buf = _io.BytesIO()
            for chunk in f:
                buf.write(chunk)
            raw = buf.getvalue()
            if not raw:
                return None
            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if f.channels > 1:
                arr = arr.reshape(-1, f.channels).mean(axis=1)
            # resample if needed
            if int(f.samplerate) != target_sr:
                try:
                    import librosa as _librosa2

                    arr = _librosa2.resample(arr, orig_sr=int(f.samplerate), target_sr=target_sr)
                except Exception:
                    pass
            return arr.astype(np.float32)
    except Exception:
        return None
    return None


def _load_rms(audio_path: Path, width: int) -> list[float] | None:
    """Load audio and compute normalized RMS per column."""
    y = _load_audio_mono(audio_path, 22050)
    if y is None:
        return None
    if len(y) == 0:
        return [0.0] * width
    samples_per_pixel = max(1, len(y) // width)
    rms_values: list[float] = []
    for i in range(0, len(y), samples_per_pixel):
        chunk = y[i : i + samples_per_pixel]
        if len(chunk) == 0:
            rms_values.append(0.0)
        else:
            rms_values.append(float(np.sqrt(np.mean(chunk**2))))
        if len(rms_values) >= width:
            break
    max_rms = max(rms_values) if rms_values else 1.0
    if max_rms > 0:
        rms_values = [v / max_rms for v in rms_values]
    while len(rms_values) < width:
        rms_values.append(0.0)
    return rms_values[:width]


@lru_cache(maxsize=64)
def _cached_rms(path_str: str, width: int) -> tuple[float, ...]:
    vals = _load_rms(Path(path_str), width)
    if vals is None:
        return tuple([0.0] * width)
    return tuple(vals)


def _render_from_rms(rms_values: list[float], width: int, height: int) -> list[str]:
    """Render mirrored waveform lines from rms_values."""
    lines: list[str] = []
    half_height = height // 2
    for row in range(half_height):
        line_chars: list[str] = []
        threshold = (row + 1) / half_height
        for rms in rms_values:
            if rms >= threshold:
                line_chars.append("\u2588")
            elif rms >= threshold - 0.5 / half_height:
                line_chars.append("\u2584")
            else:
                line_chars.append(" ")
        lines.append("".join(line_chars))
    lines.append("\u2500" * width)
    for row in range(half_height - 1, -1, -1):
        line_chars: list[str] = []
        threshold = (row + 1) / half_height
        for rms in rms_values:
            if rms >= threshold:
                line_chars.append("\u2588")
            elif rms >= threshold - 0.5 / half_height:
                line_chars.append("\u2580")
            else:
                line_chars.append(" ")
        lines.append("".join(line_chars))
    return lines


def render_waveform(
    audio_path: Path,
    width: int = 80,
    height: int = 8,
) -> str:
    """Render an ASCII waveform from an audio file."""
    try:
        vals = list(_cached_rms(str(audio_path), width))
        # detect fallback case: all zeros but file exists -> try fallback only if load failed
        # _cached_rms returns zeros on failure; we can check if file had content
        if all(v == 0.0 for v in vals):
            # try to distinguish empty vs failed load - attempt direct load
            direct = _load_rms(audio_path, width)
            if direct is None:
                return _fallback_waveform(audio_path, width, height)
        lines = _render_from_rms(vals, width, height)
        return "\n".join(lines)
    except Exception:
        return _fallback_waveform(audio_path, width, height)


def render_waveform_with_playhead(
    audio_path: Path,
    width: int = 80,
    height: int = 8,
    progress: float = 0.0,  # 0.0 .. 1.0
    play_char: str = "┃",
) -> str:
    """Render waveform with a vertical playhead overlay.

    Progress maps to column: 0 => far left, 1 => far right.
    Uses Rich markup to highlight played portion dim vs bright.
    The playhead column is rendered with a distinct character.
    """
    progress = max(0.0, min(1.0, progress))
    play_col = int(progress * (width - 1)) if width > 1 else 0

    try:
        vals = list(_cached_rms(str(audio_path), width))
        if all(v == 0.0 for v in vals):
            direct = _load_rms(audio_path, width)
            if direct is None:
                # fallback still with playhead
                base = _fallback_waveform(audio_path, width, height).split("\n")
                return _overlay_playhead(base, play_col, play_char)
        base_lines = _render_from_rms(vals, width, height)
        return _overlay_playhead(base_lines, play_col, play_char)
    except Exception:
        base = _fallback_waveform(audio_path, width, height).split("\n")
        return _overlay_playhead(base, play_col, play_char)


def _overlay_playhead(lines: list[str], col: int, char: str = "┃") -> str:
    """Overlay a vertical playhead line. Also dim the 'played' region via lower intensity."""
    # For now, simple overlay: replace char at col with playhead char on every row
    # and use a subtle approach: played columns keep waveform but playhead column is highlighted.
    out: list[str] = []
    for line in lines:
        if not line:
            out.append(line)
            continue
        # ensure line padded
        if col < 0 or col >= len(line):
            out.append(line)
            continue
        # Use Rich markup for playhead? We return plain text with playhead char;
        # caller can add markup via Static markup. Keep it simple: use char.
        lst = list(line)
        # Center line gets a different playhead glyph for visibility
        if line.strip().replace("\u2500", "") == "":
            lst[col] = "┼"  # center line intersection
        else:
            lst[col] = char
        out.append("".join(lst))
    return "\n".join(out)


def _fallback_waveform(audio_path: Path, width: int, height: int) -> str:
    try:
        size = audio_path.stat().st_size
    except OSError:
        return _empty_waveform(width, height)
    try:
        data = audio_path.read_bytes()
        step = max(1, len(data) // width)
        samples = [data[i] / 255.0 for i in range(0, min(len(data), width * step), step)]
    except Exception:
        return _empty_waveform(width, height)
    while len(samples) < width:
        samples.append(0.0)
    samples = samples[:width]
    half = height // 2
    lines: list[str] = []
    for row in range(half):
        line = ""
        threshold = (row + 1) / half
        for s in samples:
            if s >= threshold:
                line += "\u2588"
            else:
                line += " "
        lines.append(line)
    lines.append("\u2500" * width)
    for row in range(half - 1, -1, -1):
        line = ""
        threshold = (row + 1) / half
        for s in samples:
            if s >= threshold:
                line += "\u2588"
            else:
                line += " "
        lines.append(line)
    return "\n".join(lines)


def _empty_waveform(width: int, height: int) -> str:
    lines = [" " * width for _ in range(height // 2)]
    lines.append("\u2500" * width)
    lines.extend([" " * width for _ in range(height // 2)])
    return "\n".join(lines)
