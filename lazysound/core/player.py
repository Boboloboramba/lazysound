"""Audio playback engine with sounddevice backend + librosa/soundfile decoding."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable

import numpy as np


class PlaybackState(Enum):
    STOPPED = auto()
    PLAYING = auto()
    PAUSED = auto()


@dataclass
class PlaybackInfo:
    path: Path | None = None
    duration: float = 0.0  # seconds
    position: float = 0.0  # seconds
    state: PlaybackState = PlaybackState.STOPPED
    samplerate: int = 0
    channels: int = 0


def _load_audio(path: Path) -> tuple[np.ndarray, int]:
    """Load audio file to numpy array (samples, channels) + sr.

    Tries soundfile first (wav/flac/aiff/ogg), then audioread (mp3/m4a/opus via ffmpeg),
    then ffmpeg direct decode as last resort.
    """
    # try soundfile (libsndfile) – fast for wav/flac/aiff/ogg
    try:
        import soundfile as sf

        data, sr = sf.read(str(path), always_2d=True)  # (samples, channels)
        return data.astype(np.float32), int(sr)
    except Exception:
        pass

    # try audioread (handles mp3/m4a/aac/opus via ffmpeg/gstreamer)
    try:
        import audioread

        with audioread.audio_open(str(path)) as f:
            sr = int(f.samplerate)
            channels = int(f.channels)
            # audioread yields raw 16-bit PCM bytes
            import io as _io

            buf = _io.BytesIO()
            for chunk in f:
                buf.write(chunk)
            raw = buf.getvalue()
            if not raw:
                raise RuntimeError("audioread returned no data")
            # convert int16 -> float32
            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            # de-interleave
            if channels > 1:
                arr = arr.reshape(-1, channels)
            else:
                arr = arr[:, np.newaxis]
            return arr, sr
    except Exception:
        pass

    # last resort: decode via ffmpeg to wav in memory and read via soundfile
    try:
        import subprocess
        import soundfile as sf
        import io as _io
        import tempfile
        import os as _os

        # ffmpeg -> wav s16le on stdout
        # probe sr/channels first via ffprobe? Instead let ffmpeg output at original sr and parse?
        # Use ffmpeg to output wav to temp file then read.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "quiet", "-i", str(path), "-f", "wav", "-acodec", "pcm_s16le", tmp_path],
                check=True,
            )
            data, sr = sf.read(tmp_path, always_2d=True)
            return data.astype(np.float32), int(sr)
        finally:
            try:
                _os.unlink(tmp_path)
            except Exception:
                pass
    except Exception as e:
        raise RuntimeError(f"Cannot decode {path}: {e}") from e
    raise RuntimeError(f"Cannot decode {path}: all backends failed")


class AudioPlayer:
    """Thread-safe audio player using sounddevice.

    If sounddevice/PortAudio is unavailable, gracefully degrades to no-op
    (UI still functional, waveform/progress work but no audible output).
    """

    def __init__(self, on_state_change: Callable[[PlaybackInfo], None] | None = None) -> None:
        self._data: np.ndarray | None = None
        self._sr: int = 0
        self._channels: int = 0
        self._duration: float = 0.0
        self._position: int = 0  # sample index
        self._state: PlaybackState = PlaybackState.STOPPED
        self._stream = None
        self._lock = threading.Lock()
        self._path: Path | None = None
        self._volume: float = 1.0
        self._on_state_change = on_state_change
        self._has_sounddevice = self._probe_sounddevice()

    def _probe_sounddevice(self) -> bool:
        try:
            import sounddevice  # noqa: F401
            return True
        except Exception:
            return False

    # -- public API --

    @property
    def info(self) -> PlaybackInfo:
        with self._lock:
            pos_sec = self._position / self._sr if self._sr else 0.0
            return PlaybackInfo(
                path=self._path,
                duration=self._duration,
                position=pos_sec,
                state=self._state,
                samplerate=self._sr,
                channels=self._channels,
            )

    @property
    def is_playing(self) -> bool:
        return self._state == PlaybackState.PLAYING

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, v: float) -> None:
        self._volume = max(0.0, min(1.0, v))

    def load(self, path: Path) -> float:
        """Load file. Returns duration in seconds. Stops any playback."""
        self.stop()
        data, sr = _load_audio(path)
        duration = len(data) / sr if sr else 0.0
        with self._lock:
            self._data = data
            self._sr = sr
            self._channels = data.shape[1] if data.ndim > 1 else 1
            self._duration = duration
            self._position = 0
            self._path = path
            self._state = PlaybackState.STOPPED
        self._notify()
        return duration

    def play(self) -> bool:
        """Start or resume playback. Returns True if started."""
        with self._lock:
            if self._data is None or self._sr == 0:
                return False
            if self._state == PlaybackState.PLAYING:
                return True
            # if at end, restart
            if self._position >= len(self._data):
                self._position = 0
            self._state = PlaybackState.PLAYING

        if not self._has_sounddevice:
            # No audio device: simulate playback via timer would be done by UI;
            # we just mark as playing so UI animates. Caller will poll position manually.
            self._notify()
            return True

        # start stream if needed
        try:
            self._ensure_stream()
            # sounddevice stream is already running; callback will emit audio
        except Exception:
            # Stream failed (no device) -> keep simulated mode
            self._has_sounddevice = False

        self._notify()
        return True

    def pause(self) -> None:
        with self._lock:
            if self._state == PlaybackState.PLAYING:
                self._state = PlaybackState.PAUSED
        self._notify()

    def stop(self) -> None:
        with self._lock:
            self._state = PlaybackState.STOPPED
            self._position = 0
        self._close_stream()
        self._notify()

    def seek(self, seconds: float) -> None:
        """Seek to position in seconds."""
        with self._lock:
            if self._sr == 0 or self._data is None:
                return
            target = int(seconds * self._sr)
            target = max(0, min(target, len(self._data)))
            self._position = target
        self._notify()

    def seek_relative(self, delta_seconds: float) -> None:
        info = self.info
        self.seek(info.position + delta_seconds)

    def tick(self, dt: float) -> None:
        """Advance simulated position when no sounddevice (called by UI timer)."""
        if self._has_sounddevice:
            return
        with self._lock:
            if self._state != PlaybackState.PLAYING or self._data is None:
                return
            self._position += int(dt * self._sr)
            if self._position >= len(self._data):
                self._position = len(self._data)
                self._state = PlaybackState.STOPPED
        self._notify()

    # -- internal --

    def _notify(self) -> None:
        if self._on_state_change:
            try:
                self._on_state_change(self.info)
            except Exception:
                pass

    def _ensure_stream(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd

        def callback(outdata, frames, time_info, status):  # noqa: ANN001
            with self._lock:
                if self._state != PlaybackState.PLAYING or self._data is None:
                    outdata.fill(0)
                    return
                start = self._position
                end = start + frames
                total = len(self._data)
                if start >= total:
                    outdata.fill(0)
                    # schedule stop on main thread
                    self._position = total
                    return
                chunk = self._data[start:min(end, total)]
                # apply volume
                if self._volume != 1.0:
                    chunk = chunk * self._volume
                # handle channel mismatch
                out_ch = outdata.shape[1]
                data_ch = chunk.shape[1] if chunk.ndim > 1 else 1
                if data_ch == out_ch:
                    outdata[: len(chunk)] = chunk
                elif data_ch == 1 and out_ch == 2:
                    outdata[: len(chunk), 0] = chunk[:, 0]
                    outdata[: len(chunk), 1] = chunk[:, 0]
                elif data_ch == 2 and out_ch == 1:
                    outdata[: len(chunk), 0] = chunk.mean(axis=1)
                else:
                    # best effort: fill first channels, zero rest
                    n = min(data_ch, out_ch)
                    outdata[: len(chunk), :n] = chunk[:, :n] if chunk.ndim > 1 else chunk[:, None]
                    if out_ch > n:
                        outdata[: len(chunk), n:] = 0

                if len(chunk) < frames:
                    outdata[len(chunk) :] = 0
                    self._position = total
                    # mark stopped after buffer drains; UI will detect via position==duration
                else:
                    self._position = end
                # detect end-of-file
                if self._position >= total:
                    # don't change state inside audio thread; let UI poll and stop?
                    # we set paused so callback goes silent, UI timer will call stop
                    pass

        # Use original samplerate; let PortAudio handle it
        self._stream = sd.OutputStream(
            samplerate=self._sr,
            channels=self._channels,
            callback=callback,
            finished_callback=None,
        )
        self._stream.start()

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def cleanup(self) -> None:
        self._close_stream()
