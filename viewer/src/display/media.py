"""Media display mode (Viewer design §4.2): video (plays once) and still image.

Emits `finished` when a video reaches its end (so the window can return to the
idle background) and `failed(code, message)` on load/playback errors.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QStackedWidget, QWidget

import assets
import protocol


def _fit_within(size: QSize, box: QSize) -> QSize:
    """Scale *size* to fit inside *box*, preserving aspect ratio."""
    scale = min(box.width() / size.width(), box.height() / size.height())
    return QSize(max(1, round(size.width() * scale)),
                 max(1, round(size.height() * scale)))


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

        self._video = QVideoWidget(self)
        self._video.setStyleSheet("background-color: black;")
        self._still = _StillView(self)
        self.addWidget(self._video)
        self.addWidget(self._still)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.positionChanged.connect(self._on_position)
        self._player.errorOccurred.connect(self._on_error)

        self._pending_ready = False
        self._ready_fallback = QTimer(self)
        self._ready_fallback.setSingleShot(True)
        self._ready_fallback.timeout.connect(self._mark_ready)

    # -- public API -------------------------------------------------------
    def show_video(self, path: Path) -> None:
        """Start a clip. Emits `videoReady` once the first frame is painted so
        the caller can reveal it only then — the idle background stays up until
        then, so there is never a black flash between background and video.
        """
        self.setCurrentWidget(self._video)
        self._pending_ready = True
        self._player.setSource(QUrl.fromLocalFile(str(path)))
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
        self._ready_fallback.stop()
        if self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._player.stop()
        self._player.setSource(QUrl())

    # -- signals ----------------------------------------------------------
    def _on_position(self, pos: int) -> None:
        # First non-zero position means a frame has been presented.
        if pos > 0:
            self._mark_ready()

    def _on_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.BufferedMedia:
            self._mark_ready()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.finished.emit()

    def _on_error(self, error: QMediaPlayer.Error, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        self._pending_ready = False
        self._ready_fallback.stop()
        self.failed.emit(protocol.UNSUPPORTED_MEDIA, message or "playback error")
