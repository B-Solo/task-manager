"""Wire protocol constants and helpers for the Viewer.

Mirrors docs/protocol-design.md. Kept self-contained so the Viewer is an
independent deploy unit (no shared import with the Controller).
"""

from __future__ import annotations

import json
from typing import Any

# Transport
PORT = 8765
MAX_MESSAGE_BYTES = 1 * 1024 * 1024  # 1 MiB (protocol §2 Robustness)

# Commands (Controller -> Viewer)
GET_CATALOGUE = "get_catalogue"
SHOW_MEDIA = "show_media"
BACKGROUND = "background"
SHOW_LEADERBOARD = "show_leaderboard"
SHOW_SERIES_LEADERBOARD = "show_series_leaderboard"

COMMANDS = {
    GET_CATALOGUE,
    SHOW_MEDIA,
    BACKGROUND,
    SHOW_LEADERBOARD,
    SHOW_SERIES_LEADERBOARD,
}

# Messages (Viewer -> Controller)
CATALOGUE = "catalogue"
ERROR = "error"

# Error codes (protocol §6.2)
NOT_FOUND = "not_found"
UNSUPPORTED_MEDIA = "unsupported_media"
BAD_REQUEST = "bad_request"
UNKNOWN_TYPE = "unknown_type"
TOO_LARGE = "too_large"
INTERNAL = "internal"


def error_message(
    ref: int | None,
    code: str,
    message: str,
    command: str | None = None,
) -> dict[str, Any]:
    """Build an `error` envelope (§6.2)."""
    payload: dict[str, Any] = {"ref": ref, "code": code, "message": message}
    if command is not None:
        payload["command"] = command
    return {"type": ERROR, "payload": payload}


def catalogue_message(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a `catalogue` envelope (§6.1). Viewer-initiated: no `id`."""
    return {"type": CATALOGUE, "payload": payload}


def dumps(message: dict[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False)
