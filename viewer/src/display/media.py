"""Media display mode (Viewer design §4.2): video (plays once) and still image.

Emits `finished` when a video reaches its end (so the window can return to the
idle background) and `failed(code, message)` on load/playback errors.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImageReader, QPainter, QPixmap
from PySide6.QtMultimedia import (
    QAudioOutput,
    QMediaPlayer,
    QVideoFrame,
    QVideoSink,
)
from PySide6.QtWidgets import QStackedWidget, QWidget

import assets
import protocol


def _fit_within(size: QSize, box: QSize) -> QSize:
    """Scale *size* to fit inside *box*, preserving aspect ratio."""
    scale = min(box.width() / size.width(), box.height() / size.height())
    return QSize(max(1, round(size.width() * scale)),
                 max(1, round(size.height() * scale)))


class _VideoSurface(QWidget):
    """Paints the player's video frames ourselves via a QVideoSink.

    We drive the player through a QVideoSink (rather than a QVideoWidget) for one
    key reason: it lets us **keep the last decoded frame on screen**. A plain
    QVideoWidget blanks to black the instant playback ends, which made the
    end-of-clip "freeze on the final frame" show black instead. Here the last
    valid frame is retained until we explicitly clear it, so the freeze is
    pixel-accurate. As a bonus, the first frame's arrival is the exact moment
    it's safe to reveal the video (no black flash on the way in).

    Video fills the screen preserving aspect ratio (contained, centred on
    black) — matching the authored 16:9 clips, never cropped or stretched.
    """

    frameArrived = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.sink = QVideoSink(self)
        self.sink.videoFrameChanged.connect(self._on_frame)
        self._frame = QVideoFrame()

    def _on_frame(self, frame: QVideoFrame) -> None:
        # Ignore the invalid/empty frame some backends emit at end-of-stream, so
        # the final real frame stays put for the freeze.
        if frame.isValid() and not frame.size().isEmpty():
            self._frame = frame
            self.update()
            self.frameArrived.emit()

    def has_frame(self) -> bool:
        return self._frame.isValid()

    def clear(self) -> None:
        self._frame = QVideoFrame()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if not self._frame.isValid():
            return
        fsize = self._frame.size()
        if fsize.isEmpty():
            return
        target = _fit_within(fsize, self.size())
        x = (self.width() - target.width()) / 2
        y = (self.height() - target.height()) / 2
        self._frame.paint(
            painter,
            QRectF(x, y, target.width(), target.height()),
            QVideoFrame.PaintOptions(),
        )


class _StillView(QWidget):
    """Full-screen still, contained (fit whole image) and centred on black.

    Never crops or rotates: a portrait photo simply shows with black to the
    left/right rather than being cropped or flipped.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QPainter

        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._pixmap.isNull():
            return
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)


class MediaView(QStackedWidget):
    finished = Signal()  # a video ended on its own
    failed = Signal(str, str)  # (error_code, message)
    videoReady = Signal()  # first frame is on screen (safe to reveal)

    # Fallback delay before revealing a video even if we never saw the first
    # frame report (guards against a clip that never advances position).
    READY_FALLBACK_MS = 500

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background-color: black;")

        self._video = _VideoSurface(self)
        self._still = _StillView(self)
        self.addWidget(self._video)
        self.addWidget(self._still)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoSink(self._video.sink)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._video.frameArrived.connect(self._mark_ready)
        self._player.errorOccurred.connect(self._on_error)

        self._pending_ready = False
        # When a lead-in (preroll) is playing, this holds the main clip to play
        # straight after it — see show_video()/_on_status().
        self._next_path: Path | None = None
        self._ready_fallback = QTimer(self)
        self._ready_fallback.setSingleShot(True)
        self._ready_fallback.timeout.connect(self._mark_ready)

    # -- public API -------------------------------------------------------
    def show_video(self, path: Path, preroll: Path | None = None) -> None:
        """Start a clip. Emits `videoReady` once the first frame is painted so
        the caller can reveal it only then — the idle background stays up until
        then, so there is never a black flash between background and video.

        If *preroll* is given, that (series-wide) clip plays first and, the
        instant it ends, we cut straight into *path* with **no** end-of-clip
        freeze and no black in between: the preroll's last frame stays up until
        the main clip's first frame arrives. Only the main clip's end triggers
        `finished` (and thus the normal 1 s hold).
        """
        self.setCurrentWidget(self._video)
        self._video.clear()  # drop any previous clip's frozen final frame
        self._pending_ready = True
        if preroll is not None:
            self._next_path = path
            first = preroll
        else:
            self._next_path = None
            first = path
        self._player.setSource(QUrl.fromLocalFile(str(first)))
        self._player.play()
        self._ready_fallback.start(self.READY_FALLBACK_MS)

    def _mark_ready(self) -> None:
        if self._pending_ready:
            self._pending_ready = False
            self._ready_fallback.stop()
            self.videoReady.emit()

    def show_still(self, path: Path) -> bool:
        """Load and display a still. Returns False if the image failed to load.

        Uses QImageReader with auto-transform so EXIF-rotated photos (e.g.
        phone portraits) display upright rather than sideways. SVGs are vector,
        so they are rendered up to the TV resolution instead of their small
        intrinsic size, keeping them crisp full-screen.
        """
        self.stop()
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        if path.suffix.lower() == ".svg":
            intrinsic = reader.size()
            if intrinsic.isValid() and not intrinsic.isEmpty():
                reader.setScaledSize(_fit_within(intrinsic, QSize(1920, 1080)))
        image = reader.read()
        if image.isNull():
            return False
        self._still.set_pixmap(QPixmap.fromImage(image))
        self.setCurrentWidget(self._still)
        return True

    def stop(self) -> None:
        self._pending_ready = False
        self._next_path = None
        self._ready_fallback.stop()
        if self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._player.stop()
        self._player.setSource(QUrl())
        self._video.clear()

    # -- signals ----------------------------------------------------------
    def _on_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.BufferedMedia:
            self._mark_ready()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._next_path is not None:
                # A lead-in just ended: chain straight into the main clip with
                # no freeze and no black. Deliberately do NOT clear the surface,
                # so the preroll's last frame holds until the main clip paints.
                nxt, self._next_path = self._next_path, None
                self._player.setSource(QUrl.fromLocalFile(str(nxt)))
                self._player.play()
            else:
                self.finished.emit()

    def _on_error(self, error: QMediaPlayer.Error, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        self._pending_ready = False
        self._ready_fallback.stop()
        self.failed.emit(protocol.UNSUPPORTED_MEDIA, message or "playback error")
