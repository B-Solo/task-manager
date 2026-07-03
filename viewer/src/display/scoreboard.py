"""Leaderboard display mode (Viewer design §4.3–§4.4, §5–§6).

Episode and series boards share this one implementation. The board is laid out
in a fixed logical coordinate system (ported from the VodBox reference) and
scaled to the TV via QGraphicsView, drawn over the typewriter background plate.
A single master timer drives the hold → count-up + reorder + leader-scale
animation, and keeps the frame wobble running for as long as the board is up.
For the series board the wax seal crossfades from the *previous* leader to the
*current* leader as the scores settle, so the new leader isn't revealed early.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsItemGroup,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QWidget,
)

import assets

# Logical layout (Viewer design §5.1)
COLUMN_W = 205
PITCH = 275
X_OFFSET = 30
FRAME_H = 250
MARGIN_BELOW_FRAME = 25
INSET = 33
REFERENCE_COUNT = 5
LOGICAL_H = 1080
SCORE_FONT_PX = 84

# The wax-seal artwork's visual centre as a fraction of its bounding box
# (measured from the alpha of seal.png): the number sits here, not at the
# geometric box centre, so it reads as centred inside the seal.
SEAL_CX_FRAC = 0.53
SEAL_CY_FRAC = 0.52

# Timeline (Viewer design §6), milliseconds
HOLD_MS = 1000
ANIMATE_MS = 2000

# Wobble (§5.3)
WOBBLE_DEG = 4.0
WOBBLE_PERIOD_MS = 3000
WOBBLE_STAGGER_MS = 1250


def _ease(t: float) -> float:
    """Reference ease(): quadratic in/out on [0, 1]."""
    return 2 * t * t if t < 0.5 else -1 + (4 - 2 * t) * t


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


@dataclass
class _Row:
    cid: str
    name: str
    previous: float
    current: float
    # graphics
    root: QGraphicsItemGroup
    scaler: QGraphicsItemGroup
    container: QGraphicsItemGroup
    seal_gold: QGraphicsPixmapItem
    score_text: QGraphicsSimpleTextItem
    # animation state
    prev_x: float = 0.0
    cur_x: float = 0.0
    prev_scale: float = 1.0
    cur_scale: float = 1.0
    prev_gold: float = 0.0
    cur_gold: float = 0.0
    phase: float = field(default=0.0)


def _load_contestant_names() -> dict[str, str]:
    path = assets.asset_abs(assets.CONTESTANTS_JSON)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {c["id"]: c.get("name", c["id"]) for c in data.get("contestants", [])}


def _leader_scale(score: float, max_score: float, tied_at_top: int) -> float:
    if score != max_score:
        return 1.0
    return 1.2 if tied_at_top <= 2 else 1.1


class Scoreboard(QGraphicsView):
    def __init__(self, font_family: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setStyleSheet("border: 0px; background-color: black;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._names = _load_contestant_names()
        self._font_family = font_family
        self._frame_pm = self._load_asset(assets.SCOREBOARD_FRAME, COLUMN_W)
        self._seal_red = self._load_asset(assets.SEAL_RED, COLUMN_W)
        self._seal_gold = self._load_asset(assets.SEAL_GOLD, COLUMN_W)
        self._seal_h = self._seal_red.height() if not self._seal_red.isNull() else 120
        self._bg_pixmap = QPixmap(str(assets.asset_abs(assets.SCOREBOARD_BACKGROUND)))

        self._rows: list[_Row] = []
        self._wm = 1400.0

        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    # -- background -------------------------------------------------------
    def drawBackground(self, painter, rect) -> None:  # noqa: N802
        """Fill the whole viewport with the typewriter plate (cover-scaled)."""
        painter.save()
        painter.resetTransform()
        vp = self.viewport().rect()
        painter.fillRect(vp, QColor("black"))
        if not self._bg_pixmap.isNull():
            scaled = self._bg_pixmap.scaled(
                vp.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (scaled.width() - vp.width()) // 2
            y = (scaled.height() - vp.height()) // 2
            painter.drawPixmap(0, 0, scaled, x, y, vp.width(), vp.height())
        painter.restore()

    # -- asset helpers ----------------------------------------------------
    @staticmethod
    def _load_asset(rel: str, width: int) -> QPixmap:
        pm = QPixmap(str(assets.asset_abs(rel)))
        if pm.isNull():
            return pm
        return pm.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)

    def _load_portrait(self, cid: str) -> QPixmap:
        path = assets.asset_abs(f"assets/contestants/{cid}.png")
        pm = QPixmap(str(path))
        inset_w, inset_h = COLUMN_W - 2 * INSET, FRAME_H - 2 * INSET
        if pm.isNull():
            placeholder = QPixmap(inset_w, inset_h)
            placeholder.fill(QColor(60, 60, 60))
            return placeholder
        scaled = pm.scaled(
            inset_w, inset_h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (scaled.width() - inset_w) // 2
        y = (scaled.height() - inset_h) // 2
        return scaled.copy(x, y, inset_w, inset_h)

    # -- public API -------------------------------------------------------
    def set_scores(self, scores: list[dict], series: bool) -> None:
        """Show a leaderboard and (re)start the animation. `scores` is a list of
        {contestant, previous, current}. `series` toggles the gold-seal rule.
        """
        self._timer.stop()
        self._scene.clear()
        self._rows = []

        self._wm = 1400.0 * (len(scores) / REFERENCE_COUNT) if scores else 1400.0
        content_h = FRAME_H + MARGIN_BELOW_FRAME + self._seal_h + SCORE_FONT_PX
        y0 = (LOGICAL_H - content_h) / 2

        for entry in scores:
            self._rows.append(self._build_row(entry, y0))

        self._compute_layout(series)
        self._scene.setSceneRect(QRectF(0, 0, self._wm, LOGICAL_H))
        self._fit()

        # Initial frame: previous order, previous scores, previous gold state.
        for row in self._rows:
            row.root.setX(row.prev_x)
            row.scaler.setScale(row.prev_scale)
            row.seal_gold.setOpacity(row.prev_gold)
            self._set_score_text(row, row.previous)
        self._clock.restart()
        self._timer.start()

    # -- layout & rows ----------------------------------------------------
    def _build_row(self, entry: dict, y0: float) -> _Row:
        cid = entry["contestant"]
        name = self._names.get(cid, cid)

        root = QGraphicsItemGroup()
        root.setPos(0, y0)
        self._scene.addItem(root)

        scaler = QGraphicsItemGroup(root)
        container = QGraphicsItemGroup(scaler)

        portrait = QGraphicsPixmapItem(self._load_portrait(cid), container)
        portrait.setPos(INSET, INSET)
        portrait.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        if not self._frame_pm.isNull():
            frame = QGraphicsPixmapItem(self._frame_pm, container)
            frame.setPos(0, 0)
            frame.setTransformationMode(Qt.TransformationMode.SmoothTransformation)

        # Transform origins: the frame wobbles about its own centre; the whole
        # column (frame + seal + score) scales about the column's visual centre
        # so a leader grows/shrinks in place rather than sliding.
        container.setTransformOriginPoint(COLUMN_W / 2, FRAME_H / 2)
        column_h = FRAME_H + MARGIN_BELOW_FRAME + self._seal_h
        scaler.setTransformOriginPoint(COLUMN_W / 2, column_h / 2)

        seal_y = FRAME_H + MARGIN_BELOW_FRAME
        # Red seal underneath (always opaque); gold on top with animated opacity.
        # Seals and score live under the scaler so the leader emphasis applies
        # to the entire column, not just the portrait frame.
        seal_red = QGraphicsPixmapItem(self._seal_red, scaler)
        seal_red.setPos(0, seal_y)
        seal_red.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        seal_gold = QGraphicsPixmapItem(self._seal_gold, scaler)
        seal_gold.setPos(0, seal_y)
        seal_gold.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        seal_gold.setOpacity(0.0)

        score_text = QGraphicsSimpleTextItem("0", scaler)
        font = QFont(self._font_family) if self._font_family else QFont()
        font.setPixelSize(SCORE_FONT_PX)
        score_text.setFont(font)
        score_text.setBrush(QBrush(QColor("white")))
        score_text.setPen(QPen(Qt.PenStyle.NoPen))

        return _Row(
            cid=cid, name=name,
            previous=float(entry.get("previous", 0)),
            current=float(entry.get("current", 0)),
            root=root, scaler=scaler, container=container,
            seal_gold=seal_gold, score_text=score_text,
        )

    def _compute_layout(self, series: bool) -> None:
        def order(key):
            return sorted(self._rows, key=lambda r: (key(r), r.name.lower()))

        for idx, row in enumerate(order(lambda r: r.previous)):
            row.prev_x = PITCH * idx + X_OFFSET
        for idx, row in enumerate(order(lambda r: r.current)):
            row.cur_x = PITCH * idx + X_OFFSET

        self._assign_scales(lambda r: r.previous, "prev_scale")
        self._assign_scales(lambda r: r.current, "cur_scale")

        for idx, row in enumerate(order(lambda r: r.current)):
            row.phase = -idx * WOBBLE_STAGGER_MS

        # Gold seal for the series leader(s): previous state at the start,
        # current state at the end. Episode boards never go gold.
        if series and not self._seal_gold.isNull():
            self._assign_gold(lambda r: r.previous, "prev_gold")
            self._assign_gold(lambda r: r.current, "cur_gold")

    def _assign_scales(self, key, attr: str) -> None:
        if not self._rows:
            return
        max_score = max(key(r) for r in self._rows)
        tied = sum(1 for r in self._rows if key(r) == max_score)
        for row in self._rows:
            setattr(row, attr, _leader_scale(key(row), max_score, tied))

    def _assign_gold(self, key, attr: str) -> None:
        max_score = max((key(r) for r in self._rows), default=0.0)
        for row in self._rows:
            setattr(row, attr, 1.0 if (max_score > 0 and key(row) == max_score) else 0.0)

    def _set_score_text(self, row: _Row, value: float) -> None:
        text = str(int(round(value)))
        row.score_text.setText(text)
        # Centre the glyph *ink* (tight bounding box) on the seal's visual
        # centre. Using the item's full boundingRect instead would leave the
        # number sitting high because the font's descent padding is empty for
        # digits.
        fm = QFontMetricsF(row.score_text.font())
        tight = fm.tightBoundingRect(text)
        ink_cx = tight.x() + tight.width() / 2
        ink_cy = fm.ascent() + tight.y() + tight.height() / 2
        target_x = COLUMN_W * SEAL_CX_FRAC
        target_y = FRAME_H + MARGIN_BELOW_FRAME + self._seal_h * SEAL_CY_FRAC
        row.score_text.setPos(target_x - ink_cx, target_y - ink_cy)

    # -- animation --------------------------------------------------------
    def _tick(self) -> None:
        t = self._clock.elapsed()

        # Wobble runs for as long as the board is on screen.
        for row in self._rows:
            angle = WOBBLE_DEG * math.sin(
                2 * math.pi * ((t + row.phase) % WOBBLE_PERIOD_MS) / WOBBLE_PERIOD_MS
            )
            row.container.setRotation(angle)

        if t < HOLD_MS:
            return  # holding on the previous standings

        q = min((t - HOLD_MS) / ANIMATE_MS, 1.0)
        pos_e = _smoothstep(q)
        score_e = _ease(q)
        for row in self._rows:
            row.root.setX(_lerp(row.prev_x, row.cur_x, pos_e))
            row.scaler.setScale(_lerp(row.prev_scale, row.cur_scale, pos_e))
            row.seal_gold.setOpacity(_lerp(row.prev_gold, row.cur_gold, score_e))
            self._set_score_text(row, _lerp(row.previous, row.current, score_e))
        # timer keeps running so the wobble continues after the count settles

    # -- scaling ----------------------------------------------------------
    def _fit(self) -> None:
        self.setSceneRect(QRectF(0, 0, self._wm, LOGICAL_H))
        self.fitInView(QRectF(0, 0, self._wm, LOGICAL_H),
                       Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def stop(self) -> None:
        self._timer.stop()
