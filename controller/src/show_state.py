"""Show state: per-episode scores + progress, fold-in, and series derivation.

See docs/high-level-design.md §5 and docs/controller-design.md §9. There is no
season-level file — series totals are derived from the per-episode states.
Pure logic (no Qt), so it is unit-testable headlessly.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("controller.state")

LIVE_TASK = "live_task"

# ui_page values (Controller design §9)
PAGE_HOME = "home"
PAGE_EPISODE_INTRO = "episode_intro"
PAGE_OPENING_BIT = "opening_bit"
PAGE_PLAYBACK = "playback"
PAGE_SCORING = "scoring"
PAGE_SCOREBOARD_PREP = "scoreboard_prep"
PAGE_POST_DISPLAY = "post_display"
PAGE_SERIES_DISPLAY = "series_display"
PAGE_PRE_OUTRO = "pre_outro"
PAGE_LIVE_TASK = "live_task"
PAGE_LIVE_SCORING = "live_scoring"

CONFIG_DIR = (Path(__file__).resolve().parent.parent / "config").resolve()
EPISODES_DIR = CONFIG_DIR / "episodes"


def _zero(ids: list[str]) -> dict[str, int]:
    return {cid: 0 for cid in ids}


@dataclass
class EpisodeState:
    episode_id: str
    contestant_ids: list[str]
    segment: str = ""
    step_index: int = 0
    ui_page: str = PAGE_EPISODE_INTRO
    previous_totals: dict[str, int] = field(default_factory=dict)
    task_scores: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Ensure every contestant has an entry in both sets.
        for cid in self.contestant_ids:
            self.previous_totals.setdefault(cid, 0)
            self.task_scores.setdefault(cid, 0)

    # -- scoring ----------------------------------------------------------
    def combined(self) -> dict[str, int]:
        """previous + task per contestant (the episode's current standings)."""
        return {
            cid: self.previous_totals.get(cid, 0) + self.task_scores.get(cid, 0)
            for cid in self.contestant_ids
        }

    def set_task_score(self, cid: str, value: int) -> None:
        self.task_scores[cid] = value

    def fold_in(self) -> None:
        """Fold task scores into previous totals and reset task scores (§4.3)."""
        for cid in self.contestant_ids:
            self.previous_totals[cid] = (
                self.previous_totals.get(cid, 0) + self.task_scores.get(cid, 0)
            )
            self.task_scores[cid] = 0

    # -- serialisation ----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "segment": self.segment,
            "step_index": self.step_index,
            "ui_page": self.ui_page,
            "previous_totals": self.previous_totals,
            "task_scores": self.task_scores,
        }

    @classmethod
    def from_dict(cls, episode_id: str, ids: list[str], data: dict) -> "EpisodeState":
        return cls(
            episode_id=episode_id,
            contestant_ids=ids,
            segment=data.get("segment", ""),
            step_index=data.get("step_index", 0),
            ui_page=data.get("ui_page", PAGE_EPISODE_INTRO),
            previous_totals=dict(data.get("previous_totals", {})),
            task_scores=dict(data.get("task_scores", {})),
        )


def ranking(totals: dict[str, int], names: dict[str, str]) -> list[tuple[str, int]]:
    """(contestant_id, total) sorted by total desc, then name asc (tie-break)."""
    return sorted(
        totals.items(),
        key=lambda kv: (-kv[1], names.get(kv[0], kv[0]).lower()),
    )


def scores_payload(
    previous: dict[str, int], current: dict[str, int], ids: list[str]
) -> list[dict]:
    """Build the leaderboard `scores` array (order is irrelevant; Viewer sorts)."""
    return [
        {"contestant": cid,
         "previous": previous.get(cid, 0),
         "current": current.get(cid, 0)}
        for cid in ids
    ]


class ShowStore:
    """Loads/saves per-episode states and derives series standings."""

    def __init__(self, contestant_ids: list[str], names: dict[str, str],
                 episode_ids: list[str]) -> None:
        self.contestant_ids = contestant_ids
        self.names = names
        self.episode_ids = episode_ids

    def _path(self, ep_id: str) -> Path:
        return EPISODES_DIR / ep_id / "show_state.json"

    def load_episode(self, ep_id: str) -> EpisodeState:
        path = self._path(ep_id)
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return EpisodeState.from_dict(ep_id, self.contestant_ids, data)
            except (OSError, json.JSONDecodeError) as exc:
                log.error("Episode state %s unreadable, starting fresh: %s", ep_id, exc)
        return EpisodeState(episode_id=ep_id, contestant_ids=self.contestant_ids)

    def save_episode(self, state: EpisodeState) -> None:
        path = self._path(state.episode_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _episode_combined_from_disk(self, ep_id: str) -> dict[str, int]:
        path = self._path(ep_id)
        if not path.is_file():
            return _zero(self.contestant_ids)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _zero(self.contestant_ids)
        prev = data.get("previous_totals", {})
        task = data.get("task_scores", {})
        return {cid: prev.get(cid, 0) + task.get(cid, 0) for cid in self.contestant_ids}

    def series_scores(self, current: EpisodeState) -> list[dict]:
        """Derive the series `scores` array (HLD §5).

        current = sum of every episode's combined totals;
        previous = same sum excluding the currently open episode.
        The open episode uses the live in-memory state, not what's on disk.
        """
        previous_totals = _zero(self.contestant_ids)
        current_totals = _zero(self.contestant_ids)
        for ep_id in self.episode_ids:
            if ep_id == current.episode_id:
                combined = current.combined()
                include_in_previous = False
            else:
                combined = self._episode_combined_from_disk(ep_id)
                include_in_previous = True
            for cid in self.contestant_ids:
                current_totals[cid] += combined[cid]
                if include_in_previous:
                    previous_totals[cid] += combined[cid]
        return scores_payload(previous_totals, current_totals, self.contestant_ids)

    def reset_series(self) -> None:
        """Delete every episode's saved state (development aid)."""
        if not EPISODES_DIR.is_dir():
            return
        for ep_id in self.episode_ids:
            path = self._path(ep_id)
            if path.is_file():
                path.unlink()
                log.info("Reset: removed %s", path)

    def series_current_totals(self) -> dict[str, int]:
        """Series standings across all episodes as stored on disk (for home)."""
        totals = _zero(self.contestant_ids)
        for ep_id in self.episode_ids:
            combined = self._episode_combined_from_disk(ep_id)
            for cid in self.contestant_ids:
                totals[cid] += combined[cid]
        return totals
