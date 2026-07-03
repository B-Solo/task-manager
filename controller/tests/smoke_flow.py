"""Headless smoke test: drive the Controller through a full episode flow with a
stub network client, asserting the emitted wire commands and that every page
renders without error. Run offscreen:

    QT_QPA_PLATFORM=offscreen python controller/tests/smoke_flow.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication  # noqa: E402

import catalogue as cat_mod  # noqa: E402
import protocol  # noqa: E402
import show_state as st  # noqa: E402
from catalogue import Catalogue  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


class StubClient:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._host = "stub"

    def send(self, message: dict) -> bool:
        self.sent.append(message)
        return True


def last_types(client: StubClient, n: int) -> list[str]:
    return [m["type"] for m in client.sent[-n:]]


def main() -> int:
    cached = cat_mod.load_cached()
    assert cached is not None, "run the catalogue-cache generation step first"

    # Redirect state persistence to a temp dir.
    tmp = Path(tempfile.mkdtemp(prefix="tm-smoke-"))
    st.EPISODES_DIR = tmp / "episodes"

    app = QApplication.instance() or QApplication(sys.argv)
    client = StubClient()
    window = MainWindow(client, protocol.IdSequencer())
    window._init_from_catalogue(cached)
    window.render()  # home

    assert window.ep_id is None
    assert "Series standings" in _text(window)

    # --- Episode intro -> opening bit ---
    window.open_episode("ep01")
    assert window.state.ui_page == st.PAGE_EPISODE_INTRO
    window.play_intro()
    assert window.state.ui_page == st.PAGE_OPENING_BIT
    assert client.sent[-1]["type"] == protocol.SHOW_MEDIA
    assert client.sent[-1]["payload"]["path"].endswith("ep01/intro.mp4")

    # --- Prize task ---
    window.open_task("task00_prize")
    assert window.state.ui_page == st.PAGE_PLAYBACK
    steps = window._steps()
    n = len(steps)
    media_cmds = 0
    while window.state.step_index < n - 2:
        before = len(client.sent)
        window.play_next()
        if len(client.sent) > before:
            media_cmds += 1
    assert media_cmds >= 3, f"expected several clips, got {media_cmds}"

    # Score (final step is text-only for the prize task)
    window.score()
    assert window.state.ui_page == st.PAGE_SCORING
    scores = {"taylor": 4, "max": 2, "charlie": 5, "peter": 3, "harry": 1}
    for cid, v in scores.items():
        window._on_score_changed(cid, v)

    window.to_prep()
    assert window.state.ui_page == st.PAGE_SCOREBOARD_PREP
    window.display_episode_scoreboard()
    assert window.state.ui_page == st.PAGE_POST_DISPLAY
    board = client.sent[-1]
    assert board["type"] == protocol.SHOW_LEADERBOARD
    prev = {e["contestant"]: e["previous"] for e in board["payload"]["scores"]}
    cur = {e["contestant"]: e["current"] for e in board["payload"]["scores"]}
    assert prev == {c: 0 for c in scores}, prev  # prize is first task, no prior
    assert cur == scores, cur

    window.series_scoreboard()
    assert client.sent[-1]["type"] == protocol.SHOW_SERIES_LEADERBOARD

    # --- Next task folds prize in and clears the TV ---
    window.next_segment()
    # next_segment sends background, then opens task01 (no media on a text-only
    # step 0), so the last command is the background clear.
    assert client.sent[-1]["type"] == protocol.BACKGROUND
    assert window.state.segment == "task01"
    assert window.state.previous_totals == scores  # prize folded in
    assert all(v == 0 for v in window.state.task_scores.values())

    # --- Jump straight to the live task and finish the episode ---
    window.open_live_task()
    assert window.state.ui_page == st.PAGE_LIVE_TASK
    window.toggle_countdown()  # start
    assert window._countdown_timer.isActive()
    assert window._countdown_button_text() == "Pause countdown"
    window.toggle_countdown()  # pause
    assert not window._countdown_timer.isActive()
    assert window._countdown_button_text() == "Resume countdown"
    window.score_live()
    assert window.state.ui_page == st.PAGE_LIVE_SCORING
    for cid in scores:
        window._on_score_changed(cid, 3)
    window.to_prep()
    assert window.state.segment == st.LIVE_TASK
    # live prep before board shown: only Display episode scoreboard
    window.display_episode_scoreboard()
    assert window.state.ui_page == st.PAGE_POST_DISPLAY

    # --- Interstitial background between final scoreboard and outro (§f) ---
    window.to_pre_outro()
    assert window.state.ui_page == st.PAGE_PRE_OUTRO
    assert client.sent[-1]["type"] == protocol.BACKGROUND
    window.back()  # back returns to the episode scoreboard page (TV untouched)
    assert window.state.ui_page == st.PAGE_POST_DISPLAY
    window.to_pre_outro()

    window.outro()
    assert window.ep_id is None  # back home
    assert client.sent[-1]["type"] == protocol.SHOW_MEDIA
    assert client.sent[-1]["payload"]["path"].endswith("ep01/outro.mp4")

    # Series after ep01 complete: reopen ep02, series previous should equal ep01
    window.open_episode("ep02")
    series = window.store.series_scores(window.state)
    prev = {e["contestant"]: e["previous"] for e in series}
    # ep01 final = prize(scores) folded + live(all 3) = scores + 3 each
    expected_prev = {c: scores[c] + 3 for c in scores}
    assert prev == expected_prev, (prev, expected_prev)

    print("SMOKE OK — commands sent:", len(client.sent))
    print("final sent types:", last_types(client, 6))
    print("series previous after ep01:", prev)
    return 0


def _text(window: MainWindow) -> str:
    from PySide6.QtWidgets import QLabel
    return " ".join(lbl.text() for lbl in window.findChildren(QLabel))


if __name__ == "__main__":
    raise SystemExit(main())
