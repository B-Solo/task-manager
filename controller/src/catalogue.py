"""Catalogue cache and accessors for the Controller.

The catalogue is fetched from the Viewer once (protocol §5.1) and persisted to
`controller/config/catalogue.json`, then reused across reconnects/sessions.
This module wraps that payload with convenient lookups for the UI.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("controller.catalogue")

CONFIG_DIR = (Path(__file__).resolve().parent.parent / "config").resolve()
CATALOGUE_PATH = CONFIG_DIR / "catalogue.json"


class Catalogue:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    # -- contestants ------------------------------------------------------
    def contestants(self) -> list[dict[str, str]]:
        return self.payload.get("contestants", [])

    def contestant_ids(self) -> list[str]:
        return [c["id"] for c in self.contestants()]

    def contestant_names(self) -> dict[str, str]:
        return {c["id"]: c.get("name", c["id"]) for c in self.contestants()}

    # -- intros -----------------------------------------------------------
    def intros(self) -> list[dict[str, str]]:
        return self.payload.get("intros", [])

    # -- series-wide clips ------------------------------------------------
    def intro(self) -> str | None:
        """Series-wide opening intro clip (played once per episode)."""
        return self.payload.get("intro")

    def outro(self) -> str | None:
        """Series-wide closing outro clip."""
        return self.payload.get("outro")

    def task_lead_in(self) -> str | None:
        """Series-wide lead-in that precedes each task's first (video) clip."""
        return self.payload.get("task_lead_in")

    # -- episodes / tasks -------------------------------------------------
    def episodes(self) -> list[dict[str, Any]]:
        return self.payload.get("episodes", [])

    def episode_ids(self) -> list[str]:
        return [e["id"] for e in self.episodes()]

    def episode(self, ep_id: str) -> dict[str, Any] | None:
        for ep in self.episodes():
            if ep["id"] == ep_id:
                return ep
        return None

    def tasks(self, ep_id: str) -> list[dict[str, Any]]:
        ep = self.episode(ep_id)
        return ep.get("tasks", []) if ep else []

    def task(self, ep_id: str, task_id: str) -> dict[str, Any] | None:
        for task in self.tasks(ep_id):
            if task["id"] == task_id:
                return task
        return None

    # -- persistence ------------------------------------------------------
    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CATALOGUE_PATH.write_text(
            json.dumps(self.payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("Wrote catalogue to %s", CATALOGUE_PATH)


def load_cached() -> Catalogue | None:
    if not CATALOGUE_PATH.is_file():
        return None
    try:
        payload = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
        return Catalogue(payload)
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Cached catalogue unreadable: %s", exc)
        return None


def has_cache() -> bool:
    return CATALOGUE_PATH.is_file()
