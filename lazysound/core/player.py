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


def _is_html_file(path: Path) -> bool:
    try:
        sz = path.stat().st_size
        if sz == 0 or sz > 200_000:
            return False
        head = path.read_bytes()[:2048].lstrip()
        low = head[:500].lower()
        if low.startswith(b"<!doctype") or low.startswith(b"<html"):
            return True
        if b"<title>404" in low and b"<html" in low:
            return True
        return False
    except Exception:
        return False


def _get_target_sr() -> int:
    """Device's preferred samplerate, fallback to 48000."""
    try:
        import sounddevice as sd
        # Try JACK / default output device
        try:
            dev_idx = sd.default.device[1]
            if dev_idx is not None and dev_idx >= 0:
                info = sd.query_devices(dev_idx)
                sr = int(info.get("default_samplerate") or 48000)
                if 4000 <= sr <= 192000:
                    return sr
        except Exception:
            pass
        # fallback: query default output
        try:
            info = sd.query_devices(kind="output")
            sr = int(info.get("default_samplerate") or 48000)
            if 4000 <= sr <= 192000:
                return sr
        except Exception:
            pass
    except Exception:
        pass
    return 48000


def _resample_data(data: np.ndarray, src_sr: int, target_sr: int) -> np.ndarray:
    if src_sr == target_sr or data.size == 0:
        return data
    # data shape (samples, channels)
    # Try soxr (high quality, fast), fallback to librosa
    try:
        import soxr  # type: ignore

        # soxr expects (samples, channels) or (samples,)
        # Use soxr.resample for 2D? soxr 0.3+ has resample?
        # Try per-channel resample if needed
        if data.ndim == 1 or data.shape[1] == 1:
            mono = data[:, 0] if data.ndim == 2 else data
            res = soxr.resample(mono, src_sr, target_sr)  # type: ignore
            return res[:, None].astype(np.float32) if res.ndim == 1 else res.astype(np.float32)
        else:
            # per channel
            channels = []
            for ch in range(data.shape[1]):
                r = soxr.resample(data[:, ch], src_sr, target_sr)  # type: ignore
                channels.append(r)
            # all resampled channels should have same length (soxr may differ by 1)
            min_len = min(len(c) for c in channels)
            stacked = np.stack([c[:min_len] for c in channels], axis=1)
            return stacked.astype(np.float32)
    except Exception:
        pass
    try:
        import librosa

        # librosa expects (channels, samples) or (samples,)
        if data.ndim == 2:
            # process per channel to keep shape (samples, channels)
            out_channels = []
            for ch in range(data.shape[1]):
                y = librosa.resample(data[:, ch], orig_sr=src_sr, target_sr=target_sr)  # type: ignore
                out_channels.append(y)
            min_len = min(len(c) for c in out_channels)
            stacked = np.stack([c[:min_len] for c in out_channels], axis=1)
            return stacked.astype(np.float32)
        else:
            y = librosa.resample(data, orig_sr=src_sr, target_sr=target_sr)  # type: ignore
            return y.astype(np.float32)[:, None]
    except Exception:
        # fallback: no resample
        return data


def _load_audio(path: Path) -> tuple[np.ndarray, int]:
    """Load audio file to numpy array (samples, channels) + sr."""
    if _is_html_file(path):
        try:
            sz = path.stat().st_size
        except Exception:
            sz = 0
        msg = f"File is HTML (likely 404 page, {sz} bytes) not audio — not decodable. Path: {path}. Remove or re-download."
        raise RuntimeError(msg)
    try:
        import soundfile as sf

        data, sr = sf.read(str(path), always_2d=True)
        return data.astype(np.float32), int(sr)
    except Exception:
        pass
    try:
        import audioread

        with audioread.audio_open(str(path)) as f:
            sr = int(f.samplerate)
            channels = int(f.channels)
            import io as _io

            buf = _io.BytesIO()
            for chunk in f:
                buf.write(chunk)
            raw = buf.getvalue()
            if not raw:
                raise RuntimeError("audioread returned no data")
            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if channels > 1:
                arr = arr.reshape(-1, channels)
            else:
                arr = arr[:, np.newaxis]
            return arr, sr
    except Exception:
        pass
    try:
        import subprocess
        import soundfile as sf
        import tempfile
        import os as _os

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
        msg = f"Cannot decode {path.name}: {e} (all backends failed — file may be corrupted, truncated, or unsupported codec)"
        raise RuntimeError(msg) from e
    msg = f"Cannot decode {path.name}: all backends failed"
    raise RuntimeError(msg)


class AudioPlayer:
    """Thread-safe audio player using sounddevice. Handles resampling to device rate to avoid choppy playback."""

    def __init__(self, on_state_change: Callable[[PlaybackInfo], None] | None = None) -> None:
        self._data: np.ndarray | None = None  # (samples, channels) float32, already resampled to target
        self._sr: int = 0  # target sr (device)
        self._orig_sr: int = 0
        self._channels: int = 0  # target channels (usually 2)
        self._duration: float = 0.0
        self._position: int = 0
        self._state: PlaybackState = PlaybackState.STOPPED
        self._stream = None
        self._lock = threading.Lock()
        self._path: Path | None = None
        self._volume: float = 1.0
        self._on_state_change = on_state_change
        self._has_sounddevice = self._probe_sounddevice()
        self._target_sr: int = _get_target_sr()
        self._underflow_count: int = 0

    def _probe_sounddevice(self) -> bool:
        try:
            import sounddevice  # noqa: F401

            return True
        except Exception:
            return False

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
        data, orig_sr = _load_audio(path)
        # Resample to device rate to avoid choppy (device may not support 22k/11k well)
        target_sr = self._target_sr
        # Update target in case device changed
        try:
            target_sr = _get_target_sr()
            self._target_sr = target_sr
        except Exception:
            pass
        if orig_sr != target_sr:
            try:
                data = _resample_data(data, orig_sr, target_sr)
                sr = target_sr
            except Exception:
                sr = orig_sr
        else:
            sr = orig_sr
        # Normalize channels: ensure stereo (2) for device compatibility, or keep mono if file is mono but device supports it
        # We will keep original channels but ensure at least 1 and at most 2 for most devices
        # Convert mono -> stereo by duplicating for smoother device handling (many devices expect stereo)
        channels = data.shape[1] if data.ndim > 1 else 1
        if channels == 1:
            # duplicate mono to stereo for device that prefers stereo (avoids channel mismatch choppiness)
            try:
                data = np.repeat(data, 2, axis=1)
                channels = 2
            except Exception:
                pass
        elif channels > 2:
            # downmix to stereo if >2 (e.g., 5.1) – simple
            try:
                # if 6 channels, take mean of front?
                data = data[:, :2]  # take first 2
                channels = 2
            except Exception:
                pass
        # ensure contiguous float32
        try:
            data = np.ascontiguousarray(data, dtype=np.float32)
        except Exception:
            data = data.astype(np.float32)

        duration = len(data) / sr if sr else 0.0
        with self._lock:
            self._data = data
            self._sr = sr
            self._orig_sr = orig_sr
            self._channels = channels
            self._duration = duration
            self._position = 0
            self._path = path
            self._state = PlaybackState.STOPPED
        self._notify()
        return duration

    def play(self) -> bool:
        with self._lock:
            if self._data is None or self._sr == 0:
                return False
            if self._state == PlaybackState.PLAYING:
                return True
            if self._position >= len(self._data):
                self._position = 0
            self._state = PlaybackState.PLAYING
        if not self._has_sounddevice:
            self._notify()
            return True
        try:
            self._ensure_stream()
        except Exception:
            self._has_sounddevice = False
            # fallback to simulated
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

    def _notify(self) -> None:
        if self._on_state_change:
            try:
                self._on_state_change(self.info)
            except Exception:
                pass

    def _ensure_stream(self) -> None:
        # If stream exists but SR/channels changed, recreate
        if self._stream is not None:
            try:
                # check if stream params match current file
                # sounddevice doesn't expose easily, so check our stored _stream samplerate via _sr
                # We store target sr, so if stream was created with old sr, we need new
                # Simplest: if stream exists, assume it's correct (since we close on stop/load)
                return
            except Exception:
                pass
        import sounddevice as sd

        # Use explicit dtype, blocksize, latency for smooth playback
        def callback(outdata, frames, time_info, status):  # noqa: ANN001
            # Log underflows for debugging choppy
            if status and status.output_underflow:
                self._underflow_count += 1
                # don't spam logs, just count
                pass
            # Fast path: copy without holding lock long
            # We need to snapshot position and data reference under lock, then copy outside?
            # But we need to ensure position update is atomic
            # Use lock only for position/state, copy outside
            with self._lock:
                if self._state != PlaybackState.PLAYING or self._data is None:
                    outdata.fill(0)
                    return
                start = self._position
                total = len(self._data)
                if start >= total:
                    outdata.fill(0)
                    self._position = total
                    return
                # determine chunk to copy (avoid holding lock during copy)
                end = start + frames
                # clip
                chunk_end = end if end < total else total
                # we will copy outside lock? Need data reference
                data_ref = self._data
                # reserve position advance
                # we will update position after copy
                # to avoid race, we copy chunk now while holding lock (small)
                chunk = data_ref[start:chunk_end]
                # copy logic will be done after releasing lock? But we need outdata shape
                # Keep lock for entire copy to ensure position not changed mid-copy (seek)
                # It's okay to hold lock for ~ frames (2048*2 float32 ~ 16KB copy) ~ microseconds
                out_ch = outdata.shape[1]
                data_ch = chunk.shape[1] if chunk.ndim > 1 else 1
                # handle volume and channel
                if self._volume != 1.0:
                    # need to not modify original data, so copy
                    chunk = chunk * self._volume
                if data_ch == out_ch:
                    outdata[: len(chunk)] = chunk
                elif data_ch == 1 and out_ch == 2:
                    # mono -> stereo already handled at load, but keep fallback
                    outdata[: len(chunk), 0] = chunk[:, 0]
                    outdata[: len(chunk), 1] = chunk[:, 0]
                elif data_ch == 2 and out_ch == 1:
                    outdata[: len(chunk), 0] = chunk.mean(axis=1)
                else:
                    n = min(data_ch, out_ch)
                    outdata[: len(chunk), :n] = chunk[:, :n] if chunk.ndim > 1 else chunk[:, None]
                    if out_ch > n:
                        outdata[: len(chunk), n:] = 0
                if len(chunk) < frames:
                    outdata[len(chunk) :] = 0
                    self._position = total
                else:
                    self._position = end

        # Choose blocksize and latency for low choppiness
        # 2048 at 48k ~ 42ms, good balance
        self._stream = sd.OutputStream(
            samplerate=self._sr,
            channels=self._channels,
            dtype="float32",
            blocksize=2048,
            latency="low",
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
