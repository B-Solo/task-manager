"""Top-level full-screen window and display-mode switching (Viewer design §3).

Owns the three display modes (background, media, scoreboard) in a
QStackedWidget so exactly one is visible at a time. This matters because
QVideoWidget uses a native window that would otherwise float above sibling
widgets; hiding the non-current modes is what guarantees a clean return to the
idle background after a clip ends or is cancelled.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

import assets
import protocol
from display.background import BackgroundView
from display.media import MediaView
from display.scoreboard import Scoreboard

log = logging.getLogger("viewer.window")

# How long to hold on a video's final frame before returning to the idle
# background when a clip ends on its own (§4.2).
FREEZE_ON_END_MS = 1000


class ViewerWindow(QWidget):
    send_message = Signal(dict)  # error envelopes back to the Controller

    def __init__(self, font_family: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Taskmaster Viewer")
        self.setStyleSheet("background-color: black;")
        self.setCursor(Qt.CursorShape.BlankCursor)

        self._stack = QStackedWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._background = BackgroundView()
        self._media = MediaView()
        self._scoreboard = Scoreboard(font_family)
        for mode in (self._background, self._media, self._scoreboard):
            self._stack.addWidget(mode)

        self._media.finished.connect(self._on_video_finished)
        self._media.failed.connect(self._on_media_failed)
        self._media.videoReady.connect(self._on_video_ready)
        self._media_ref: int | None = None
        self._media_command: str | None = None
        # A video was requested but is not yet revealed (still buffering its
        # first frame). We hold on the background until videoReady fires.
        self._pending_video_reveal = False

        # Holds the last video frame for a beat after a clip ends before we cut
        # back to the idle background.
        self._freeze_timer = QTimer(self)
        self._freeze_timer.setSingleShot(True)
        self._freeze_timer.timeout.connect(self._end_freeze)

        self._show_mode(self._background)

    def _show_mode(self, widget: QWidget) -> None:
        self._stack.setCurrentWidget(widget)

    @property
    def _current(self) -> QWidget:
        return self._stack.currentWidget()

    # -- command dispatch (runs on the GUI thread) ------------------------
    def handle_command(self, message: dict) -> None:
        mtype = message.get("type")
        if mtype == protocol.TOGGLE_PLAYBACK:
            # Passive play/pause: it must not disturb the display-mode state
            # machine nor cancel a pending end-of-clip freeze, so handle it up
            # front. A no-op unless a video is actually mid-playback.
            self._media.toggle_pause()
            return
        # Any new command cancels a pending end-of-clip freeze.
        self._freeze_timer.stop()
        try:
            if mtype == protocol.SHOW_MEDIA:
                self._do_show_media(message)
            elif mtype == protocol.BACKGROUND:
                self._do_background()
            elif mtype == protocol.SHOW_LEADERBOARD:
                self._do_leaderboard(message, series=False)
            elif mtype == protocol.SHOW_SERIES_LEADERBOARD:
                self._do_leaderboard(message, series=True)
            else:
                # get_catalogue is handled in the network layer; anything else
                # here is a programming error.
                log.warning("Window received unexpected command %r", mtype)
        except Exception as exc:  # fail loudly to the Controller, never to TV
            log.exception("Command %r failed", mtype)
            self._error(message.get("id"), protocol.INTERNAL, str(exc), mtype)

    def _do_show_media(self, message: dict) -> None:
        ref = message.get("id")
        path_rel = (message.get("payload") or {}).get("path")
        if not path_rel or not isinstance(path_rel, str):
            self._error(ref, protocol.BAD_REQUEST, "show_media requires a 'path'",
                        protocol.SHOW_MEDIA)
            return
        try:
            resolved = assets.resolve_media(path_rel)
        except assets.PathEscapeError as exc:
            self._error(ref, protocol.BAD_REQUEST, str(exc), protocol.SHOW_MEDIA)
            return
        if not resolved.is_file():
            self._error(ref, protocol.NOT_FOUND, f"File not found: {path_rel}",
                        protocol.SHOW_MEDIA)
            return

        if assets.is_video(resolved):
            self._media_ref = ref
            self._media_command = protocol.SHOW_MEDIA
            preroll = self._resolve_preroll(message, ref)
            # Keep the current mode (background/last clip) visible and only cut
            # to the video once its first frame is ready — no black flash.
            self._pending_video_reveal = True
            self._media.show_video(resolved, preroll=preroll)
        elif assets.is_image(resolved):
            self._pending_video_reveal = False
            if not self._media.show_still(resolved):
                self._error(ref, protocol.UNSUPPORTED_MEDIA,
                            f"Could not load image: {path_rel}", protocol.SHOW_MEDIA)
                return
            self._show_mode(self._media)
        else:
            self._error(ref, protocol.UNSUPPORTED_MEDIA,
                        f"Unsupported media type: {path_rel}", protocol.SHOW_MEDIA)

    def _resolve_preroll(self, message: dict, ref):
        """Resolve an optional series-wide lead-in for a video command.

        Best-effort: a lead-in that is missing or not a video is reported to the
        Controller but never blocks the main clip — the show goes on.
        """
        preroll_rel = (message.get("payload") or {}).get("preroll")
        if not preroll_rel or not isinstance(preroll_rel, str):
            return None
        try:
            resolved = assets.resolve_media(preroll_rel)
        except assets.PathEscapeError as exc:
            self._error(ref, protocol.BAD_REQUEST, str(exc), protocol.SHOW_MEDIA)
            return None
        if not resolved.is_file() or not assets.is_video(resolved):
            self._error(ref, protocol.NOT_FOUND,
                        f"Lead-in unavailable, playing clip alone: {preroll_rel}",
                        protocol.SHOW_MEDIA)
            return None
        return resolved

    def _do_background(self) -> None:
        self._pending_video_reveal = False
        self._show_mode(self._background)
        self._media.stop()
        self._scoreboard.stop()

    def _do_leaderboard(self, message: dict, series: bool) -> None:
        ref = message.get("id")
        cmd = protocol.SHOW_SERIES_LEADERBOARD if series else protocol.SHOW_LEADERBOARD
        scores = (message.get("payload") or {}).get("scores")
        if not isinstance(scores, list) or not scores:
            self._error(ref, protocol.BAD_REQUEST, f"{cmd} requires 'scores'", cmd)
            return
        for entry in scores:
            if "contestant" not in entry:
                self._error(ref, protocol.BAD_REQUEST,
                            "each score needs a 'contestant'", cmd)
                return
        self._pending_video_reveal = False
        self._scoreboard.set_scores(scores, series=series)
        self._show_mode(self._scoreboard)
        self._media.stop()

    # -- media signals ----------------------------------------------------
    def _on_video_ready(self) -> None:
        # First frame is painted: safe to cut from the background to the clip.
        if self._pending_video_reveal:
            self._pending_video_reveal = False
            self._show_mode(self._media)

    def _on_video_finished(self) -> None:
        # Hold on the final frame for a beat, then return to the idle background
        # (§4.2). We deliberately do NOT stop the player yet: leaving the ended
        # clip loaded keeps its last frame on screen during the freeze.
        if self._current is self._media:
            self._freeze_timer.start(FREEZE_ON_END_MS)

    def _end_freeze(self) -> None:
        # Freeze elapsed: cut to the background, then release the player.
        if self._current is self._media:
            self._show_mode(self._background)
            self._media.stop()

    def _on_media_failed(self, code: str, msg: str) -> None:
        self._pending_video_reveal = False
        self._freeze_timer.stop()
        self._error(self._media_ref, code, msg, self._media_command)
        self._show_mode(self._background)
        self._media.stop()

    # -- errors -----------------------------------------------------------
    def _error(self, ref, code: str, message: str, command: str | None) -> None:
        log.warning("error ref=%s code=%s: %s", ref, code, message)
        self.send_message.emit(protocol.error_message(ref, code, message, command))
