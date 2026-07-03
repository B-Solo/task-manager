"""Wire protocol constants and outbound-message builders for the Controller.

Mirrors docs/protocol-design.md. Self-contained so the Controller is an
independent deploy unit.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

PORT = 8765

# Commands (Controller -> Viewer)
GET_CATALOGUE = "get_catalogue"
SHOW_MEDIA = "show_media"
BACKGROUND = "background"
SHOW_LEADERBOARD = "show_leaderboard"
SHOW_SERIES_LEADERBOARD = "show_series_leaderboard"

# Messages (Viewer -> Controller)
CATALOGUE = "catalogue"
ERROR = "error"


class IdSequencer:
    """Monotonically increasing message id per session, starting at 1 (§3)."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def next(self) -> int:
        return next(self._counter)


def _envelope(mtype: str, msg_id: int | None, payload: dict[str, Any]) -> dict[str, Any]:
    env: dict[str, Any] = {"type": mtype}
    if msg_id is not None:
        env["id"] = msg_id
    env["payload"] = payload
    return env


def get_catalogue(msg_id: int) -> dict[str, Any]:
    return _envelope(GET_CATALOGUE, msg_id, {})


def show_media(msg_id: int, path: str) -> dict[str, Any]:
    return _envelope(SHOW_MEDIA, msg_id, {"path": path})


def background(msg_id: int) -> dict[str, Any]:
    return _envelope(BACKGROUND, msg_id, {})


def show_leaderboard(msg_id: int, scores: list[dict]) -> dict[str, Any]:
    return _envelope(SHOW_LEADERBOARD, msg_id, {"scores": scores})


def show_series_leaderboard(msg_id: int, scores: list[dict]) -> dict[str, Any]:
    return _envelope(SHOW_SERIES_LEADERBOARD, msg_id, {"scores": scores})


def dumps(message: dict[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False)
