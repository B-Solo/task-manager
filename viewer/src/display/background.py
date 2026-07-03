"""Idle background display mode (Viewer design §4.1).

The screen the show rests on. The backdrop asset is authored 16:9 to match the
TV, so it is simply scaled to cover the display (any tiny aspect difference
crops symmetrically and imperceptibly, preserving aspect ratio).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

import assets


class BackgroundView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: black;")
        self._pixmap = QPixmap()
        self._load()

    def _load(self) -> None:
        path = assets.asset_abs(assets.DEFAULT_BACKGROUND)
        if path.exists():
            self._pixmap = QPixmap(str(path))

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._pixmap.isNull():
            return
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (scaled.width() - self.width()) // 2
        y = (scaled.height() - self.height()) // 2
        painter.drawPixmap(0, 0, scaled, x, y, self.width(), self.height())
