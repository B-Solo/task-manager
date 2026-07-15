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
    # Intro is now series-wide, not per-episode.
    assert client.sent[-1]["payload"]["path"] == cached.intro()
    assert client.sent[-1]["payload"]["path"].startswith("series/")

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
    # Fold-in captured the prize task's per-contestant breakdown for analytics.
    assert window.state.task_breakdown.get("task00_prize") == scores, \
        window.state.task_breakdown

    # --- A studio task's first clip is a video intro: playing forward into it
    # prepends the series-wide lead-in as a preroll (only on forward play). ---
    lead = cached.task_lead_in()
    first_idx = window._first_media_index()
    window.play_next()
    intro_cmd = client.sent[-1]
    assert intro_cmd["type"] == protocol.SHOW_MEDIA
    if lead and window.state.step_index == first_idx:
        assert intro_cmd["payload"].get("preroll") == lead, intro_cmd
    # 'Play specific' of that same clip must NOT carry the lead-in.
    window.play_specific(first_idx)
    assert "preroll" not in client.sent[-1]["payload"], client.sent[-1]

    # --- Pause/play toggle: fire-and-forget, empty payload, and it must not
    # disturb the TV indicator (the Controller can't know the playback state). ---
    assert window.tv_kind == "video"
    tv_before = (window.tv_kind, window.tv_label)
    window.toggle_playback()
    assert client.sent[-1]["type"] == protocol.TOGGLE_PLAYBACK
    assert client.sent[-1]["payload"] == {}
    assert (window.tv_kind, window.tv_label) == tv_before

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
    # Outro is now series-wide, not per-episode.
    assert client.sent[-1]["payload"]["path"] == cached.outro()
    assert client.sent[-1]["payload"]["path"].startswith("series/")

    # ep01's saved state carries the full per-task breakdown (analytics).
    ep01_saved = window.store.load_episode("ep01")
    assert ep01_saved.task_breakdown.get("task00_prize") == scores
    assert ep01_saved.task_breakdown.get("live_task") == {c: 3 for c in scores}, \
        ep01_saved.task_breakdown

    # Series after ep01 complete: reopen ep02, series previous should equal ep01
    window.open_episode("ep02")
    series = window.store.series_scores(window.state)
    prev = {e["contestant"]: e["previous"] for e in series}
    # ep01 final = prize(scores) folded + live(all 3) = scores + 3 each
    expected_prev = {c: scores[c] + 3 for c in scores}
    assert prev == expected_prev, (prev, expected_prev)

    # Per-episode reset wipes only that episode; others stay put.
    window.reset_episode("ep01")
    assert not (st.EPISODES_DIR / "ep01" / "show_state.json").is_file()
    assert (st.EPISODES_DIR / "ep02" / "show_state.json").is_file()

    # --- Dry run: in-memory scores, nothing written, auto-clears on home ---
    window.go_home()
    assert not window.dry_run
    window.toggle_dry_run()
    assert window.dry_run
    window.open_episode("ep01")          # reset above -> no file on disk
    window.state.set_task_score("taylor", 5)
    window._persist()                    # would save normally; must no-op here
    assert window.state.task_scores["taylor"] == 5   # kept for the run
    assert not (st.EPISODES_DIR / "ep01" / "show_state.json").is_file(), \
        "dry run must never write to disk"
    window.go_home()
    assert not window.dry_run            # a dry run ends with the episode

    print("SMOKE OK — commands sent:", len(client.sent))
    print("final sent types:", last_types(client, 6))
    print("series previous after ep01:", prev)
    return 0


def _text(window: MainWindow) -> str:
    from PySide6.QtWidgets import QLabel
    return " ".join(lbl.text() for lbl in window.findChildren(QLabel))


if __name__ == "__main__":
    raise SystemExit(main())
