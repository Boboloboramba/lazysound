"""ASCII waveform renderer for terminal display."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np


# Block characters for waveform rendering (low to high amplitude)
BLOCKS = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"


def render_waveform(
    audio_path: Path,
    width: int = 80,
    height: int = 8,
) -> str:
    """Render an ASCII waveform from an audio file.

    Args:
        audio_path: Path to audio file.
        width: Character width of output.
        height: Number of rows for waveform.

    Returns:
        Multi-line string of the ASCII waveform.
    """
    try:
        import librosa
        import soundfile as sf

        # Load audio (mono, downsampled for speed)
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    except Exception:
        return _fallback_waveform(audio_path, width, height)

    if len(y) == 0:
        return _empty_waveform(width, height)

    # Resample to target width
    samples_per_pixel = max(1, len(y) // width)
    chunks = [
        y[i : i + samples_per_pixel] for i in range(0, len(y), samples_per_pixel)
    ]

    # Compute RMS per chunk
    rms_values = []
    for chunk in chunks:
        if len(chunk) == 0:
            rms_values.append(0.0)
        else:
            rms_values.append(float(np.sqrt(np.mean(chunk**2))))

    # Normalize
    max_rms = max(rms_values) if rms_values else 1.0
    if max_rms > 0:
        rms_values = [v / max_rms for v in rms_values]

    # Pad or trim to width
    while len(rms_values) < width:
        rms_values.append(0.0)
    rms_values = rms_values[:width]

    # Render as mirrored block characters
    lines: list[str] = []
    half_height = height // 2

    for row in range(half_height):
        line_chars: list[str] = []
        threshold = (row + 1) / half_height
        for rms in rms_values:
            if rms >= threshold:
                line_chars.append("\u2588")  # Full block for upper half
            elif rms >= threshold - 0.5 / half_height:
                line_chars.append("\u2584")  # Lower half block
            else:
                line_chars.append(" ")
        lines.append("".join(line_chars))

    # Center line
    center_line = "\u2500" * width
    lines.append(center_line)

    # Mirror (bottom half)
    for row in range(half_height - 1, -1, -1):
        line_chars: list[str] = []
        threshold = (row + 1) / half_height
        for rms in rms_values:
            if rms >= threshold:
                line_chars.append("\u2588")
            elif rms >= threshold - 0.5 / half_height:
                line_chars.append("\u2580")  # Upper half block
            else:
                line_chars.append(" ")
        lines.append("".join(line_chars))

    return "\n".join(lines)


def _fallback_waveform(audio_path: Path, width: int, height: int) -> str:
    """Generate a pseudo-waveform from file size as fallback."""
    try:
        size = audio_path.stat().st_size
    except OSError:
        return _empty_waveform(width, height)

    # Use file content bytes as pseudo-samples
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
