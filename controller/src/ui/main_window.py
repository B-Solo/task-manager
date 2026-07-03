"""Controller main window: header, content, footer, and the page/navigation
state machine that drives every wire command.

Implements docs/controller-design.md. One window re-renders its content and
footer from the current (episode, ui_page, segment, step) each time state
changes, rather than many separate page classes.
"""

from __future__ import annotations

import logging
import os
import random

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import protocol
import show_state as st
import style
from catalogue import Catalogue
from show_state import EpisodeState, ShowStore
from ui.widgets import ScorePicker, footer_button

log = logging.getLogger("controller.ui")

VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

LIVE_COUNTDOWN_S = 100  # season-wide constant (Controller design §5.1)


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            # Detach immediately so it stops painting this frame; deleteLater
            # alone would leave the old page visible until the event loop runs.
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


class MainWindow(QWidget):
    def __init__(self, client, sequencer: protocol.IdSequencer) -> None:
        super().__init__()
        self.client = client
        self.ids = sequencer

        self.catalogue: Catalogue | None = None
        self.store: ShowStore | None = None
        self.names: dict[str, str] = {}

        self.ep_id: str | None = None
        self.state: EpisodeState | None = None

        self.connected = False
        self.tv_kind = "idle"   # idle | video | still | board
        self.tv_label = "idle"

        self._countdown_remaining = LIVE_COUNTDOWN_S
        self._countdown_started = False  # started at least once and not finished
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdown)

        self._build_chrome()
        self.setWindowTitle("Taskmaster Control")
        self.resize(1000, 700)

    # ==================================================================
    # Chrome (header / content / footer)
    # ==================================================================
    def _build_chrome(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header. Left = controller state (where the operator is). Right = the
        # Viewer/TV state next to the connection indicator.
        header = QWidget()
        header.setStyleSheet("background:#0f1013; border-bottom:1px solid #2a2c31;")
        header.setFixedHeight(60)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 6, 20, 6)
        hl.setSpacing(18)
        self._title = QLabel("Taskmaster Control")
        self._title.setStyleSheet("font-size:19px; font-weight:bold; color:#f0f0f0;")
        self._tv = QLabel("TV: idle")
        self._tv.setStyleSheet(
            "font-size:16px; color:#d8c48a; background:#241f16;"
            " border:1px solid #4a3f28; border-radius:8px; padding:6px 12px;")
        self._conn = QLabel("\u25cf Disconnected")
        self._conn.setStyleSheet("font-size:16px; color:#e05555; font-weight:bold;")
        hl.addWidget(self._title, 1)
        hl.addWidget(self._tv, 0)
        hl.addWidget(self._conn, 0)
        root.addWidget(header)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet(
            "background:#5a1e1e; color:white; padding:6px 20px; font-size:15px;")
        self._error_label.setVisible(False)
        root.addWidget(self._error_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(32, 28, 32, 28)
        self._content_layout.setSpacing(16)
        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        footer = QWidget()
        footer.setStyleSheet("background:#0f1013; border-top:1px solid #2a2c31;")
        footer.setMinimumHeight(104)
        self._footer_layout = QHBoxLayout(footer)
        self._footer_layout.setContentsMargins(20, 16, 20, 16)
        self._footer_layout.setSpacing(18)
        root.addWidget(footer)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Esc leaves full screen (and F11 toggles) so the operator/dev is never
        # trapped in a borderless window.
        key = event.key()
        if key == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
        elif key == Qt.Key.Key_F11:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
        else:
            super().keyPressEvent(event)

    # ==================================================================
    # Network slots
    # ==================================================================
    def set_connected(self, connected: bool) -> None:
        self.connected = connected
        if connected:
            self._conn.setText("\u25cf Connected")
            self._conn.setStyleSheet("font-size:16px; color:#5fd35f; font-weight:bold;")
            if self.catalogue is None:
                self.request_catalogue()
        else:
            self._conn.setText("\u25cf Disconnected")
            self._conn.setStyleSheet("font-size:16px; color:#e05555; font-weight:bold;")

    def on_catalogue(self, payload: dict) -> None:
        cat = Catalogue(payload)
        cat.save()
        self._init_from_catalogue(cat)
        if self.ep_id is None:
            self.render()

    def on_error(self, payload: dict) -> None:
        code = payload.get("code", "error")
        msg = payload.get("message", "")
        self._error_label.setText(f"Viewer error [{code}]: {msg}")
        self._error_label.setVisible(True)
        QTimer.singleShot(8000, lambda: self._error_label.setVisible(False))

    def request_catalogue(self) -> None:
        self.client.send(protocol.get_catalogue(self.ids.next()))

    def _init_from_catalogue(self, cat: Catalogue) -> None:
        self.catalogue = cat
        self.names = cat.contestant_names()
        self.store = ShowStore(cat.contestant_ids(), self.names, cat.episode_ids())

    # ==================================================================
    # Sending helpers (also update the TV indicator = last-command intent)
    # ==================================================================
    def _play_media(self, path: str, label: str) -> None:
        self.client.send(protocol.show_media(self.ids.next(), path))
        ext = os.path.splitext(path)[1].lower()
        self.tv_kind = "video" if ext in VIDEO_EXTS else "still"
        self.tv_label = label

    def _send_background(self) -> None:
        self.client.send(protocol.background(self.ids.next()))
        self.tv_kind, self.tv_label = "idle", "idle"

    def _send_episode_board(self) -> None:
        prev = dict(self.state.previous_totals)
        cur = self.state.combined()
        payload = st.scores_payload(prev, cur, self.store.contestant_ids)
        self.client.send(protocol.show_leaderboard(self.ids.next(), payload))
        self.tv_kind, self.tv_label = "board", "ep scorebrd"

    def _send_series_board(self) -> None:
        payload = self.store.series_scores(self.state)
        self.client.send(protocol.show_series_leaderboard(self.ids.next(), payload))
        self.tv_kind, self.tv_label = "board", "series scorebrd"

    def _arrive_text_step(self) -> None:
        # Advancing past a video: it has finished by now (operator paced).
        if self.tv_kind == "video":
            self.tv_kind, self.tv_label = "idle", "idle"

    # ==================================================================
    # Step / task helpers
    # ==================================================================
    def _steps(self) -> list[dict]:
        if not self.state or self.state.segment == st.LIVE_TASK:
            return []
        task = self.catalogue.task(self.ep_id, self.state.segment)
        return task.get("steps", []) if task else []

    @staticmethod
    def _is_media_step(step: dict) -> bool:
        return "path" in step or bool(step.get("random_intro"))

    @staticmethod
    def _step_label(step: dict) -> str:
        return step.get("clip") or "clip"

    def _resolve_media(self, step: dict) -> tuple[str | None, str]:
        """(path, label) for a media step, resolving a random intro."""
        if "path" in step:
            return step["path"], self._step_label(step)
        if step.get("random_intro"):
            pool = self.catalogue.intros()
            if pool:
                chosen = random.choice(pool)
                return chosen["path"], "intro"
            log.warning("Random intro requested but pool is empty")
        return None, self._step_label(step)

    def _persist(self) -> None:
        if self.store and self.state:
            self.store.save_episode(self.state)

    # ==================================================================
    # Display-name formatting (Controller design §4, B5 rule)
    # ==================================================================
    @staticmethod
    def _episode_display(ep_id: str) -> str:
        if ep_id.startswith("ep") and ep_id[2:].isdigit():
            return f"Ep {int(ep_id[2:]):02d}"
        return ep_id

    @staticmethod
    def _task_display(segment: str) -> str:
        if segment == st.LIVE_TASK or segment.endswith("_live"):
            return "Live task"
        if "_prize" in segment:
            return "Prize task"
        if segment.startswith("task") and segment[4:].isdigit():
            return f"Task {int(segment[4:]):02d}"
        return segment

    # ==================================================================
    # Rendering
    # ==================================================================
    def render(self) -> None:
        _clear_layout(self._content_layout)
        _clear_layout(self._footer_layout)

        if self.catalogue is None:
            self._render_waiting()
        elif self.ep_id is None:
            self._render_home()
        else:
            page = self.state.ui_page
            renderer = {
                st.PAGE_EPISODE_INTRO: self._render_episode_intro,
                st.PAGE_OPENING_BIT: self._render_opening_bit,
                st.PAGE_PLAYBACK: self._render_playback,
                st.PAGE_SCORING: self._render_scoring,
                st.PAGE_SCOREBOARD_PREP: self._render_prep,
                st.PAGE_POST_DISPLAY: self._render_post_display,
                st.PAGE_SERIES_DISPLAY: self._render_series_display,
                st.PAGE_PRE_OUTRO: self._render_pre_outro,
                st.PAGE_LIVE_TASK: self._render_live_task,
                st.PAGE_LIVE_SCORING: self._render_live_scoring,
            }.get(page, self._render_home)
            renderer()
        # Absorb spare vertical space so content sits at the top instead of
        # word-wrapped labels stretching to fill the page.
        self._content_layout.addStretch(1)
        self._update_header()

    def _update_header(self) -> None:
        # Right side always reflects the Viewer/TV state.
        self._tv.setText(f"TV: {self.tv_label}")
        # Left side reflects where the operator (controller) is.
        if self.ep_id is None or self.state is None:
            self._title.setText("Taskmaster Control")
            return
        ep = self._episode_display(self.ep_id)
        seg = self._task_display(self.state.segment) if self.state.segment else "\u2014"
        page = self.state.ui_page
        if page in (st.PAGE_PLAYBACK, st.PAGE_SCORING):
            n = len(self._steps())
            slot = f"Step {self.state.step_index + 1} of {n}"
        elif page == st.PAGE_SCOREBOARD_PREP:
            slot = "Scoreboard prep"
        elif page == st.PAGE_POST_DISPLAY:
            slot = "Episode scoreboard"
        elif page == st.PAGE_SERIES_DISPLAY:
            slot = "Series scoreboard"
        elif page == st.PAGE_PRE_OUTRO:
            slot = "Before outro"
        elif page in (st.PAGE_LIVE_TASK, st.PAGE_LIVE_SCORING):
            slot = "Live task"
        elif page == st.PAGE_EPISODE_INTRO:
            slot = "Intro"
        elif page == st.PAGE_OPENING_BIT:
            slot = "Opening bit"
        else:
            slot = ""
        self._title.setText(f"{ep}  \u00b7  {seg}  \u00b7  {slot}")

    # -- helpers to add content ------------------------------------------
    def _font(self) -> str:
        return style.NOTES_FONT_FAMILY or "Georgia"

    def _heading(self, text: str) -> None:
        label = QLabel(text)
        label.setStyleSheet(
            f'font-family:"{self._font()}"; font-size:26px; color:#e6c877;'
            " letter-spacing:1px;")
        label.setWordWrap(True)
        self._content_layout.addWidget(label)

    def _paragraph(self, text: str) -> None:
        label = QLabel(text)
        label.setStyleSheet("font-size:19px; color:#dcdcdc;")
        label.setWordWrap(True)
        self._content_layout.addWidget(label)

    def _note(self, text: str) -> None:
        """A prominent operator note (step text), in the themed typewriter font."""
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setStyleSheet(
            f'font-family:"{self._font()}"; font-size:22px; color:#f2ede0;'
            " background:#20222a; border:1px solid #33363f; border-radius:12px;"
            " padding:18px 20px;")
        label.setWordWrap(True)
        self._content_layout.addWidget(label)

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    def _render_waiting(self) -> None:
        self._heading("Waiting for catalogue…")
        self._paragraph(
            "No cached catalogue found. Connect to the Viewer to fetch it.")
        btn = footer_button("Fetch catalogue")
        btn.setEnabled(self.connected)
        btn.clicked.connect(self.request_catalogue)
        self._footer_layout.addWidget(btn)

    def _render_home(self) -> None:
        self._heading("Series standings")
        totals = self.store.series_current_totals()
        for pos, (cid, total) in enumerate(st.ranking(totals, self.names), start=1):
            self._paragraph(f"{pos}. {self.names.get(cid, cid)}   {total}")

        self._heading("Episodes")
        for ep_id in self.catalogue.episode_ids():
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            open_btn = footer_button(self._episode_display(ep_id))
            open_btn.clicked.connect(lambda _=False, e=ep_id: self.open_episode(e))
            rl.addWidget(open_btn, 1)
            jump = footer_button("Jump \u25be")
            jump.setSizePolicy(jump.sizePolicy().horizontalPolicy(),
                               jump.sizePolicy().verticalPolicy())
            jump.setMaximumWidth(160)
            jump.clicked.connect(lambda _=False, e=ep_id: self._jump_menu(e))
            self._jump_buttons = getattr(self, "_jump_buttons", {})
            self._jump_buttons[ep_id] = jump
            rl.addWidget(jump, 0)
            self._content_layout.addWidget(row)

        reset = footer_button("Reset series (dev)", danger=True)
        reset.clicked.connect(self.reset_series)
        self._footer_layout.addWidget(reset, 0)
        self._footer_layout.addStretch(1)
        refresh = footer_button("Refresh catalogue")
        refresh.setEnabled(self.connected)
        refresh.clicked.connect(self.request_catalogue)
        self._footer_layout.addWidget(refresh, 0)

    def _jump_menu(self, ep_id: str) -> None:
        menu = QMenu(self)
        for task in self.catalogue.tasks(ep_id):
            tid = task["id"]
            menu.addAction(self._task_display(tid),
                           lambda t=tid, e=ep_id: self.jump_to_task(e, t))
        menu.addAction("Live task", lambda e=ep_id: self.jump_to_live(e))
        btn = self._jump_buttons.get(ep_id)
        if btn:
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _render_episode_intro(self) -> None:
        ep = self.catalogue.episode(self.ep_id)
        self._heading(self._episode_display(self.ep_id))
        self._paragraph("Play the episode intro when ready. The opening-bit "
                        "notes will appear here while it plays.")
        play = footer_button("Play intro", big=True)
        play.setEnabled(bool(ep and ep.get("intro")))
        play.clicked.connect(self.play_intro)
        self._footer_layout.addWidget(footer_button_back(self.go_home))
        self._footer_layout.addStretch(1)
        self._footer_layout.addWidget(play)

    def _render_opening_bit(self) -> None:
        ep = self.catalogue.episode(self.ep_id)
        self._heading("Opening bit")
        text = (ep.get("opening_bit", {}) or {}).get("text", "") if ep else ""
        self._note(text or "(no opening-bit notes)")
        prize = footer_button("Prize task", big=True)
        prize.clicked.connect(lambda: self.open_task("task00_prize"))
        self._footer_layout.addWidget(footer_button_back(self.back))
        self._footer_layout.addStretch(1)
        self._footer_layout.addWidget(prize)

    def _render_playback(self) -> None:
        steps = self._steps()
        idx = self.state.step_index
        step = steps[idx]
        self._note(step.get("text", ""))
        # Next clip hint
        if idx + 1 < len(steps) and self._is_media_step(steps[idx + 1]):
            self._paragraph(f"\u25b6 Next clip: {self._step_label(steps[idx + 1])}")

        penultimate = len(steps) - 2

        self._footer_layout.addWidget(footer_button_back(self.back))
        self._footer_layout.addWidget(self._play_specific_button())
        self._footer_layout.addStretch(1)
        if self.tv_kind in ("video", "still") and idx > 0:
            cancel = footer_button("Cancel playing")
            cancel.clicked.connect(self.cancel_playing)
            self._footer_layout.addWidget(cancel)
        if idx < penultimate:
            btn = footer_button("Play next clip", big=True)
            btn.clicked.connect(self.play_next)
        else:
            btn = footer_button("Score", big=True)
            btn.clicked.connect(self.score)
        self._footer_layout.addWidget(btn)

    def _render_scoring(self) -> None:
        steps = self._steps()
        step = steps[self.state.step_index]
        if step.get("text"):
            self._note(step["text"])
        self._add_score_pickers()

        self._footer_layout.addWidget(footer_button_back(self.back))
        self._footer_layout.addWidget(self._play_specific_button())
        self._footer_layout.addStretch(1)
        if self.tv_kind in ("video", "still"):
            cancel = footer_button("Cancel playing")
            cancel.clicked.connect(self.cancel_playing)
            self._footer_layout.addWidget(cancel)
        board = footer_button("Scoreboard", big=True)
        board.clicked.connect(self.to_prep)
        self._footer_layout.addWidget(board)

    def _standings_list(self, totals: dict[str, int]) -> None:
        for pos, (cid, total) in enumerate(st.ranking(totals, self.names), start=1):
            self._paragraph(f"{pos}.  {self.names.get(cid, cid)}   \u2014   {total}")

    def _render_prep(self) -> None:
        self._heading("Episode scores")
        self._standings_list(self.state.combined())

        is_live = self.state.segment == st.LIVE_TASK
        display = footer_button("Display episode scoreboard", big=True)
        display.clicked.connect(self.display_episode_scoreboard)
        self._footer_layout.addWidget(footer_button_back(self.back))
        if not is_live:
            # Studio tasks may move on without displaying; the live task may not.
            self._footer_layout.addWidget(self._next_or_live_button())
        self._footer_layout.addStretch(1)
        self._footer_layout.addWidget(display)

    def _render_post_display(self) -> None:
        self._heading("Series standings")
        payload = self.store.series_scores(self.state)
        cur = {e["contestant"]: e["current"] for e in payload}
        self._standings_list(cur)

        self._footer_layout.addWidget(footer_button_back(self.back))
        self._footer_layout.addStretch(1)
        series = footer_button("Series scoreboard", big=True)
        series.clicked.connect(self.series_scoreboard)
        self._footer_layout.addWidget(series)
        self._footer_layout.addWidget(self._forward_button())

    def _render_series_display(self) -> None:
        self._heading("Series scoreboard (on screen)")
        payload = self.store.series_scores(self.state)
        cur = {e["contestant"]: e["current"] for e in payload}
        self._standings_list(cur)

        self._footer_layout.addWidget(footer_button_back(self.back))
        self._footer_layout.addStretch(1)
        self._footer_layout.addWidget(self._forward_button())

    def _forward_button(self) -> QPushButton:
        """The 'move on' action for the post-display / series-display pages.

        For the live task this heads to the pre-outro interstitial (which clears
        the TV to the standard background); studio tasks go to the next task /
        live task.
        """
        if self.state.segment == st.LIVE_TASK:
            btn = footer_button("Continue \u203a", big=True)
            btn.clicked.connect(self.to_pre_outro)
            return btn
        return self._next_or_live_button(big=True)

    def _render_pre_outro(self) -> None:
        """Interstitial between the final scoreboard and the outro: the TV rests
        on the standard background while the operator gets ready to roll the
        outro."""
        self._heading("Before the outro")
        self._paragraph("The TV is on the standard background. Play the outro "
                        "when you're ready to close the episode.")
        self._footer_layout.addWidget(footer_button_back(self.back))
        self._footer_layout.addStretch(1)
        out = footer_button("Play outro", big=True)
        out.clicked.connect(self.outro)
        self._footer_layout.addWidget(out)

    def _render_live_task(self) -> None:
        ep = self.catalogue.episode(self.ep_id)
        self._heading("Live task")
        text = (ep.get("live_task", {}) or {}).get("text", "") if ep else ""
        self._note(text or "(no live-task notes)")

        self._countdown_label = QLabel(self._format_countdown())
        self._countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._countdown_label.setStyleSheet(
            f'font-family:"{self._font()}"; font-size:96px; font-weight:bold;'
            " color:#e6c877; padding:12px;")
        self._content_layout.addWidget(self._countdown_label)
        self._countdown_button = footer_button(
            self._countdown_button_text(), big=True, primary=False)
        self._countdown_button.clicked.connect(self.toggle_countdown)
        self._content_layout.addWidget(self._countdown_button)

        self._footer_layout.addWidget(footer_button_back(self.back))
        self._footer_layout.addStretch(1)
        score = footer_button("Score", big=True)
        score.clicked.connect(self.score_live)
        self._footer_layout.addWidget(score)

    def _render_live_scoring(self) -> None:
        self._heading("Live task — scoring")
        self._add_score_pickers()
        self._footer_layout.addWidget(footer_button_back(self.back_live_scoring))
        self._footer_layout.addStretch(1)
        board = footer_button("Scoreboard", big=True)
        board.clicked.connect(self.to_prep)
        self._footer_layout.addWidget(board)

    # -- shared content pieces -------------------------------------------
    def _add_score_pickers(self) -> None:
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(14)
        ids = self.store.contestant_ids
        for i, cid in enumerate(ids):
            picker = ScorePicker(cid, self.names.get(cid, cid),
                                 self.state.task_scores.get(cid, 0))
            picker.changed.connect(self._on_score_changed)
            grid.addWidget(picker, i // 2, i % 2)
        self._content_layout.addWidget(grid_host)

    def _on_score_changed(self, cid: str, value: int) -> None:
        self.state.set_task_score(cid, value)
        self._persist()

    def _play_specific_button(self) -> QPushButton:
        btn = footer_button("Play specific \u25be")
        btn.setMaximumWidth(220)
        steps = self._steps()
        menu = QMenu(btn)
        for i, step in enumerate(steps):
            if self._is_media_step(step):
                menu.addAction(f"{i + 1}. {self._step_label(step)}",
                               lambda idx=i: self.play_specific(idx))
        btn.setMenu(menu)
        btn.setEnabled(menu.actions() != [])
        return btn

    def _next_or_live_button(self, big: bool = False) -> QPushButton:
        if self._has_next_task():
            btn = footer_button("Next task", big=big)
            btn.clicked.connect(self.next_segment)
        else:
            btn = footer_button("Live task", big=big)
            btn.clicked.connect(self.next_segment)
        return btn

    def _has_next_task(self) -> bool:
        tasks = [t["id"] for t in self.catalogue.tasks(self.ep_id)]
        if self.state.segment not in tasks:
            return False
        return tasks.index(self.state.segment) < len(tasks) - 1

    # ==================================================================
    # Actions
    # ==================================================================
    def go_home(self) -> None:
        self._countdown_timer.stop()
        self.ep_id = None
        self.state = None
        self.render()

    def open_episode(self, ep_id: str) -> None:
        self.ep_id = ep_id
        self.state = self.store.load_episode(ep_id)
        self.state.ui_page = st.PAGE_EPISODE_INTRO
        self.state.segment = self.state.segment or ""
        self._persist()
        self.render()

    def jump_to_task(self, ep_id: str, task_id: str) -> None:
        self.open_episode(ep_id)
        self.open_task(task_id)

    def jump_to_live(self, ep_id: str) -> None:
        self.open_episode(ep_id)
        self.open_live_task()

    def play_intro(self) -> None:
        ep = self.catalogue.episode(self.ep_id)
        intro = ep.get("intro") if ep else None
        if intro:
            self._play_media(intro, "intro")
        self.state.ui_page = st.PAGE_OPENING_BIT
        self._persist()
        self.render()

    def open_task(self, task_id: str) -> None:
        self.state.segment = task_id
        self.state.step_index = 0
        self.state.ui_page = st.PAGE_PLAYBACK
        self.tv_kind, self.tv_label = "idle", "idle"  # step 0 is text-only
        self._persist()
        self.render()

    def open_live_task(self) -> None:
        self.state.segment = st.LIVE_TASK
        self.state.ui_page = st.PAGE_LIVE_TASK
        self._countdown_timer.stop()
        self._countdown_remaining = LIVE_COUNTDOWN_S
        self._countdown_started = False
        self.tv_kind, self.tv_label = "idle", "idle"
        self._persist()
        self.render()

    def play_next(self) -> None:
        steps = self._steps()
        idx = self.state.step_index + 1
        step = steps[idx]
        if self._is_media_step(step):
            path, label = self._resolve_media(step)
            if path:
                self._play_media(path, label)
        else:
            self._arrive_text_step()
        self.state.step_index = idx
        self._persist()
        self.render()

    def play_specific(self, idx: int) -> None:
        steps = self._steps()
        step = steps[idx]
        path, label = self._resolve_media(step)
        if path:
            self._play_media(path, label)
        self.state.step_index = idx
        # layout follows whichever step Alex is on
        self.state.ui_page = (st.PAGE_SCORING if idx == len(steps) - 1
                              else st.PAGE_PLAYBACK)
        self._persist()
        self.render()

    def score(self) -> None:
        steps = self._steps()
        final = len(steps) - 1
        step = steps[final]
        if self._is_media_step(step):
            path, label = self._resolve_media(step)
            if path:
                self._play_media(path, label)
        else:
            self._arrive_text_step()
        self.state.step_index = final
        self.state.ui_page = st.PAGE_SCORING
        self._persist()
        self.render()

    def score_live(self) -> None:
        self._countdown_timer.stop()
        self.state.ui_page = st.PAGE_LIVE_SCORING
        self._persist()
        self.render()

    def cancel_playing(self) -> None:
        self._send_background()
        self.render()

    def to_prep(self) -> None:
        self.state.ui_page = st.PAGE_SCOREBOARD_PREP
        self._persist()
        self.render()

    def display_episode_scoreboard(self) -> None:
        self._send_episode_board()
        self.state.ui_page = st.PAGE_POST_DISPLAY
        self._persist()
        self.render()

    def series_scoreboard(self) -> None:
        self._send_series_board()
        self.state.ui_page = st.PAGE_SERIES_DISPLAY
        self._persist()
        self.render()

    def to_pre_outro(self) -> None:
        """Clear the TV to the standard background before the outro (§f)."""
        self._send_background()
        self.state.ui_page = st.PAGE_PRE_OUTRO
        self._persist()
        self.render()

    def reset_series(self) -> None:
        """Development aid: wipe all saved episode state and return home."""
        if self.store:
            self.store.reset_series()
        self.go_home()

    def next_segment(self) -> None:
        self.state.fold_in()
        self._send_background()
        tasks = [t["id"] for t in self.catalogue.tasks(self.ep_id)]
        if self.state.segment in tasks:
            i = tasks.index(self.state.segment)
            if i < len(tasks) - 1:
                self.open_task(tasks[i + 1])
                return
        self.open_live_task()

    def outro(self) -> None:
        self.state.fold_in()
        ep = self.catalogue.episode(self.ep_id)
        outro = ep.get("outro") if ep else None
        if outro:
            self._play_media(outro, "outro")
        self._persist()
        self.go_home()

    def back(self) -> None:
        page = self.state.ui_page
        if page == st.PAGE_OPENING_BIT:
            self.state.ui_page = st.PAGE_EPISODE_INTRO
        elif page == st.PAGE_PLAYBACK:
            if self.state.step_index > 0:
                self.state.step_index -= 1
            else:
                self.state.ui_page = st.PAGE_OPENING_BIT
        elif page == st.PAGE_SCORING:
            self.state.ui_page = st.PAGE_PLAYBACK
            self.state.step_index = max(0, len(self._steps()) - 2)
        elif page == st.PAGE_SCOREBOARD_PREP:
            # Live prep came from live scoring; studio prep from scoring.
            self.state.ui_page = (st.PAGE_LIVE_SCORING
                                  if self.state.segment == st.LIVE_TASK
                                  else st.PAGE_SCORING)
        elif page == st.PAGE_POST_DISPLAY:
            self.state.ui_page = st.PAGE_SCOREBOARD_PREP
        elif page == st.PAGE_SERIES_DISPLAY:
            self.state.ui_page = st.PAGE_POST_DISPLAY
        elif page == st.PAGE_PRE_OUTRO:
            self.state.ui_page = st.PAGE_POST_DISPLAY
        elif page == st.PAGE_LIVE_TASK:
            self.go_home()
            return
        self._persist()
        self.render()

    def back_live_scoring(self) -> None:
        self.state.ui_page = st.PAGE_LIVE_TASK
        self._persist()
        self.render()

    # -- countdown --------------------------------------------------------
    def _countdown_button_text(self) -> str:
        if self._countdown_timer.isActive():
            return "Pause countdown"
        if self._countdown_started and self._countdown_remaining > 0:
            return "Resume countdown"
        return "Start countdown"

    def toggle_countdown(self) -> None:
        """Start / pause / resume the live-task countdown on the same button."""
        if self._countdown_timer.isActive():
            self._countdown_timer.stop()  # pause (keeps remaining + started)
        else:
            if not self._countdown_started or self._countdown_remaining <= 0:
                self._countdown_remaining = LIVE_COUNTDOWN_S
                self._refresh_countdown_label()
            self._countdown_started = True
            self._countdown_timer.start()
        self._update_countdown_button()

    def _update_countdown_button(self) -> None:
        btn = getattr(self, "_countdown_button", None)
        if btn is not None:
            try:
                btn.setText(self._countdown_button_text())
            except RuntimeError:
                pass  # button was deleted on re-render

    def _refresh_countdown_label(self) -> None:
        label = getattr(self, "_countdown_label", None)
        if label is not None:
            try:
                label.setText(self._format_countdown())
            except RuntimeError:
                pass  # label was deleted on re-render

    def _tick_countdown(self) -> None:
        self._countdown_remaining -= 1
        if self._countdown_remaining <= 0:
            self._countdown_remaining = 0
            self._countdown_started = False
            self._countdown_timer.stop()
            self._update_countdown_button()  # flip back to "Start countdown"
        self._refresh_countdown_label()

    def _format_countdown(self) -> str:
        m, s = divmod(self._countdown_remaining, 60)
        return f"{m}:{s:02d}"


def footer_button_back(handler) -> QPushButton:
    btn = footer_button("\u2039 Back", primary=False)
    btn.setMaximumWidth(150)
    btn.clicked.connect(handler)
    return btn
