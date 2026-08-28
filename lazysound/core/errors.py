"""Persistent error logging for decode / IO failures."""

from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from pathlib import Path
import json

DEFAULT_ERROR_LOG = Path.home() / ".cache" / "lazysound" / "errors.log"
MAX_IN_MEMORY = 200


@dataclass
class LoggedError:
    timestamp: float
    path: str
    error: str
    context: str = ""  # e.g. "playback", "waveform", "metadata", "scan"

    def pretty_time(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.timestamp))

    def pretty_date(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))


_errors: list[LoggedError] = []


def log_error(path: Path | str, error: str, context: str = "") -> LoggedError:
    """Log error to memory and to file. Returns LoggedError."""
    entry = LoggedError(timestamp=time.time(), path=str(path), error=error, context=context)
    _errors.append(entry)
    # keep bounded
    if len(_errors) > MAX_IN_MEMORY:
        del _errors[0 : len(_errors) - MAX_IN_MEMORY]
    # also append to file
    try:
        DEFAULT_ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        # also keep human readable + json lines
        with DEFAULT_ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")
    except Exception:
        pass
    return entry


def get_recent(n: int = 100) -> list[LoggedError]:
    return list(_errors[-n:])


def clear() -> None:
    _errors.clear()
    try:
        if DEFAULT_ERROR_LOG.exists():
            DEFAULT_ERROR_LOG.unlink()
    except Exception:
        pass


def load_from_file(n: int = 100) -> list[LoggedError]:
    """Load last n errors from file if memory is empty."""
    if _errors:
        return get_recent(n)
    try:
        if not DEFAULT_ERROR_LOG.exists():
            return []
        lines = DEFAULT_ERROR_LOG.read_text(encoding="utf-8").splitlines()[-n:]
        out: list[LoggedError] = []
        for line in lines:
            try:
                d = json.loads(line)
                out.append(LoggedError(**d))
            except Exception:
                continue
        return out
    except Exception:
        return []
