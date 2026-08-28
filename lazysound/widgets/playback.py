"""Playback panel with waveform + transport controls."""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label, ProgressBar, Static

from lazysound.core.player import AudioPlayer, PlaybackInfo, PlaybackState
from lazysound.core.scanner import AudioFile
from lazysound.widgets.waveform import render_waveform_with_playhead


def _fmt_time(sec: float) -> str:
    if sec < 0 or sec != sec:  # NaN
        sec = 0
    m = int(sec) // 60
    s = int(sec) % 60
    # show milliseconds for sub-minute? keep mm:ss
    return f"{m:02d}:{s:02d}"


class PlaybackPanel(Widget):
    """Bottom docked playback UI: waveform, progress, transport."""

    DEFAULT_CSS = """
    PlaybackPanel {
        height: 11;
        dock: bottom;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
    }
    PlaybackPanel #playback-top {
        height: 1;
        width: 1fr;
    }
    PlaybackPanel #waveform {
        height: 7;
        width: 1fr;
        content-align: center middle;
        color: $success;
        background: $panel;
        border: round $secondary;
        padding: 0 1;
    }
    PlaybackPanel #transport {
        height: 3;
        width: 1fr;
        align: center middle;
    }
    PlaybackPanel Button {
        min-width: 8;
        margin: 0 1;
    }
    PlaybackPanel ProgressBar {
        width: 1fr;
        height: 1;
        margin: 0 1;
    }
    PlaybackPanel .time-label {
        width: 11;
        content-align: center middle;
        text-style: bold;
    }
    PlaybackPanel #file-label {
        width: 1fr;
        text-style: bold;
        color: $warning;
    }
    """

    current_file: reactive[AudioFile | None] = reactive(None)
    # internal
    _progress: reactive[float] = reactive(0.0)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.player = AudioPlayer(on_state_change=self._on_player_state)
        self._duration: float = 0.0
        self._auto_loaded_path: Path | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="playback-top"):
                yield Label("No file", id="file-label")
                yield Label("00:00 / 00:00", id="time-label", classes="time-label")
            yield Static("", id="waveform")
            with Horizontal(id="transport"):
                yield Button("▶ Play", id="btn-play", variant="success")
                yield Button("⏸ Pause", id="btn-pause", variant="warning")
                yield Button("■ Stop", id="btn-stop", variant="error")
                yield Button("⏮ -5s", id="btn-back")
                yield Button("⏭ +5s", id="btn-fwd")
                yield ProgressBar(total=100, show_eta=False, id="progress")

    def on_mount(self) -> None:
        self.set_interval(0.1, self._tick)

    def on_unmount(self) -> None:
        try:
            self.player.cleanup()
        except Exception:
            pass

    # -- file handling --

    def watch_current_file(self, af: AudioFile | None) -> None:
        if af is None:
            self._set_file_label("No file")
            self.query_one("#waveform", Static).update("")
            self.query_one("#progress", ProgressBar).update(progress=0)
            self.query_one("#time-label", Label).update("00:00 / 00:00")
            return
        # avoid reloading same file on every selection if already loaded
        if self._auto_loaded_path == af.path and self._duration > 0:
            self._set_file_label(af.path.name)
            self._update_waveform(0.0)
            return
        self._load_file(af)

    @work(thread=True)
    def _load_file(self, af: AudioFile) -> None:
        try:
            duration = self.player.load(af.path)
        except Exception as e:
            self.app.call_from_thread(lambda: self.app.notify(f"Cannot load {af.path.name}: {e}", severity="error"))
            return

        def _done():
            self._duration = duration
            self._auto_loaded_path = af.path
            self._set_file_label(af.path.name)
            self.query_one("#time-label", Label).update(f"00:00 / {_fmt_time(duration)}")
            self.query_one("#progress", ProgressBar).update(total=100, progress=0)
            self._update_waveform(0.0)

        self.app.call_from_thread(_done)

    def _set_file_label(self, text: str) -> None:
        try:
            self.query_one("#file-label", Label).update(text)
        except Exception:
            pass

    # -- transport actions --

    @on(Button.Pressed, "#btn-play")
    def on_play(self) -> None:
        if self.current_file is None:
            self.app.notify("No file selected", severity="warning")
            return
        # if player has no data (e.g., file changed), ensure loaded
        if self.player.info.path != self.current_file.path:
            try:
                self._duration = self.player.load(self.current_file.path)
                self._auto_loaded_path = self.current_file.path
            except Exception as e:
                self.app.notify(f"Load failed: {e}", severity="error")
                return
        ok = self.player.play()
        if ok:
            self.query_one("#btn-play", Button).label = "▶ Playing"
        else:
            self.app.notify("Cannot start playback", severity="error")

    @on(Button.Pressed, "#btn-pause")
    def on_pause(self) -> None:
        self.player.pause()
        try:
            self.query_one("#btn-play", Button).label = "▶ Play"
        except Exception:
            pass

    @on(Button.Pressed, "#btn-stop")
    def on_stop(self) -> None:
        self.player.stop()
        try:
            self.query_one("#btn-play", Button).label = "▶ Play"
        except Exception:
            pass
        self._refresh_from_player()

    @on(Button.Pressed, "#btn-back")
    def on_back(self) -> None:
        self.player.seek_relative(-5.0)
        self._refresh_from_player()

    @on(Button.Pressed, "#btn-fwd")
    def on_fwd(self) -> None:
        self.player.seek_relative(5.0)
        self._refresh_from_player()

    # -- keyboard helpers for MainScreen bindings --

    def action_play_pause(self) -> None:
        info = self.player.info
        if info.state == PlaybackState.PLAYING:
            self.on_pause()
        else:
            self.on_play()

    def action_stop(self) -> None:
        self.on_stop()

    def action_seek_back(self) -> None:
        self.on_back()

    def action_seek_forward(self) -> None:
        self.on_fwd()

    # -- waveform / progress --

    def _tick(self) -> None:
        # simulate tick when no sounddevice; also poll position
        self.player.tick(0.1)
        self._refresh_from_player()
        # auto-stop detection: if reached end, reset button label
        info = self.player.info
        if info.state == PlaybackState.STOPPED and info.position >= info.duration and info.duration > 0:
            try:
                self.query_one("#btn-play", Button).label = "▶ Play"
            except Exception:
                pass

    def _refresh_from_player(self) -> None:
        info = self.player.info
        if info.duration > 0:
            pct = (info.position / info.duration) * 100 if info.duration else 0
            pct = max(0, min(100, pct))
            try:
                self.query_one("#progress", ProgressBar).update(progress=pct)
                self.query_one("#time-label", Label).update(f"{_fmt_time(info.position)} / {_fmt_time(info.duration)}")
            except Exception:
                pass
            self._update_waveform(info.position / info.duration if info.duration else 0.0)
        # keep play button label in sync
        try:
            btn = self.query_one("#btn-play", Button)
            if info.state == PlaybackState.PLAYING:
                btn.label = "⏸ Playing"
                btn.variant = "warning"
            else:
                btn.label = "▶ Play"
                btn.variant = "success"
        except Exception:
            pass

    def _on_player_state(self, _info: PlaybackInfo) -> None:
        # called from player thread; schedule refresh on main thread
        try:
            self.app.call_from_thread(self._refresh_from_player)
        except Exception:
            pass

    def _update_waveform(self, progress: float) -> None:
        if self.current_file is None:
            return
        # width based on widget size? approximate
        try:
            w = self.query_one("#waveform", Static).size.width
            width = max(20, min(120, w - 4 if w else 80))
        except Exception:
            width = 80
        try:
            text = render_waveform_with_playhead(self.current_file.path, width=width, height=7, progress=progress)
            self.query_one("#waveform", Static).update(text)
        except Exception:
            pass

    def on_click(self, event) -> None:
        # Seek by clicking waveform: map x offset to progress
        if self._duration <= 0 or self.current_file is None:
            return
        try:
            from textual import events as _events

            if not isinstance(event, _events.Click):
                return
            wf = self.query_one("#waveform", Static)
            # check if click is inside waveform region
            if not wf.region.contains(event.screen_x, event.screen_y):
                return
            # compute relative x within widget
            rel_x = event.screen_x - wf.region.x
            w = wf.size.width
            width = max(20, min(120, w - 4 if w else 80))
            ratio = max(0.0, min(1.0, float(rel_x) / float(width)))
            self.player.seek(ratio * self._duration)
            self._refresh_from_player()
        except Exception:
            pass
