"""Reusable touch widgets for the Controller UI (Controller design §1, §11)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

# Touch-target sizes (Controller design §11)
FOOTER_MIN_H = 66
BIG_MIN_H = 96
CELL_MIN = 48


def footer_button(text: str, big: bool = False, primary: bool | None = None,
                  danger: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setMinimumHeight(BIG_MIN_H if big else FOOTER_MIN_H)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary is None:
        primary = big
    if primary:
        btn.setProperty("primary", True)
    if danger:
        btn.setProperty("danger", True)
    return btn


class ScorePicker(QWidget):
    """A contestant name plus tappable 0–5 cells (no typing), styled as a card."""

    changed = Signal(str, int)  # contestant id, value

    def __init__(self, cid: str, name: str, value: int = 0,
                 font_family: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cid = cid
        self._value = value
        self._cells: list[QPushButton] = []

        self.setObjectName("picker")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#picker { background: #20222a; border: 1px solid #33363f;"
            " border-radius: 12px; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        label = QLabel(name)
        label.setMinimumWidth(120)
        label.setStyleSheet("font-size: 21px; font-weight: bold; padding-right: 12px;"
                            + (f' font-family: "{font_family}";' if font_family else ""))
        layout.addWidget(label)
        layout.addStretch(1)

        for n in range(6):
            cell = QPushButton(str(n))
            cell.setCheckable(True)
            cell.setCursor(Qt.CursorShape.PointingHandCursor)
            cell.setMinimumSize(CELL_MIN, CELL_MIN)
            cell.setMaximumHeight(64)
            cell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            cell.clicked.connect(lambda _=False, v=n: self.set_value(v))
            layout.addWidget(cell)
            self._cells.append(cell)

        self._refresh()

    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        self._value = value
        self._refresh()
        self.changed.emit(self.cid, value)

    def _refresh(self) -> None:
        for n, cell in enumerate(self._cells):
            selected = n == self._value
            if selected:
                cell.setStyleSheet(
                    "QPushButton { font-size: 20px; font-weight: bold;"
                    " border-radius: 8px; background: #b5322f; color: white;"
                    " border: 1px solid #d24b45; }"
                )
            else:
                cell.setStyleSheet(
                    "QPushButton { font-size: 20px; border-radius: 8px;"
                    " background: #2a2d34; color: #d8d8d8; border: 1px solid #40444d; }"
                    "QPushButton:hover { background: #343842; }"
                )
            cell.setChecked(selected)
