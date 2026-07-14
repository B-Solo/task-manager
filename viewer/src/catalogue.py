"""Catalogue scan: walk `media/` and build the `catalogue` payload.

Implements the discovery rules in docs/protocol-design.md §6.1 and
docs/high-level-design.md §5. Pure-ish (filesystem only, no Qt), so it can be
unit-tested headlessly.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from assets import (
    CONTESTANTS_JSON,
    EPISODES_DIR,
    INTROS_DIR,
    MEDIA_EXTS,
    MEDIA_ROOT,
    SERIES_DIR,
)

log = logging.getLogger("viewer.catalogue")

RESERVED_INTRO = "intro"


def _rel(path: Path) -> str:
    """Path relative to the media root, using forward slashes."""
    return path.relative_to(MEDIA_ROOT).as_posix()


def _find_clip_file(folder: Path, label: str) -> Path | None:
    """First file `<label><ext>` in *folder* by extension precedence, or None.

    Labels are unique within a task folder, so precedence only matters for the
    (unexpected) case of duplicates.
    """
    for ext in MEDIA_EXTS:
        candidate = folder / f"{label}{ext}"
        if candidate.is_file():
            return candidate
    return None


def _read_text_json(path: Path) -> str:
    """Read a `{ "text": "..." }` metadata file; empty string if unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        text = data.get("text", "")
        return text if isinstance(text, str) else ""
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        log.error("Bad metadata file %s: %s", path, exc)
        return ""


def _build_step(task_dir: Path, step: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve a single results.json step into a catalogue step, or None if it
    references a clip that does not resolve to a file (omitted with a warning).
    """
    text = step.get("text", "")
    clip = step.get("clip")

    if clip is None:
        return {"text": text}

    if clip == RESERVED_INTRO:
        return _build_intro_step(task_dir, step, text)

    clip_file = _find_clip_file(task_dir, clip)
    if clip_file is None:
        log.warning("Step clip %r has no file in %s; omitting step", clip, task_dir)
        return None
    return {"clip": clip, "path": _rel(clip_file), "text": text}


def _build_intro_step(
    task_dir: Path, step: dict[str, Any], text: str
) -> dict[str, Any]:
    """Resolve the reserved `intro` step (protocol §6.1 intro-steps rule)."""
    # (1) task-specific intro file in the task folder
    own = _find_clip_file(task_dir, RESERVED_INTRO)
    if own is not None:
        return {"clip": RESERVED_INTRO, "path": _rel(own), "text": text}

    # (2) named override -> a specific clip from the shared pool
    named = step.get("intro")
    if named:
        pool_file = _find_clip_file(MEDIA_ROOT / INTROS_DIR, named)
        if pool_file is not None:
            return {"clip": RESERVED_INTRO, "path": _rel(pool_file), "text": text}
        log.warning("Named intro %r not found in pool; falling back to random", named)

    # (3) random pick left to the Controller at play time
    return {"clip": RESERVED_INTRO, "random_intro": True, "text": text}


def _build_task(task_dir: Path) -> dict[str, Any] | None:
    """Build one task object from its folder. None if results.json is invalid."""
    results = task_dir / "results.json"
    if not results.is_file():
        log.error("Task %s has no results.json; skipping", task_dir.name)
        return None
    try:
        data = json.loads(results.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Task %s results.json unreadable: %s", task_dir.name, exc)
        return None

    steps_in = data.get("steps")
    if not isinstance(steps_in, list) or len(steps_in) < 2:
        log.error("Task %s needs a steps array with >= 2 entries; skipping",
                  task_dir.name)
        return None

    if steps_in and steps_in[0].get("clip") is not None:
        log.warning("Task %s first step has a clip; it can never play", task_dir.name)

    steps_out: list[dict[str, Any]] = []
    for step in steps_in:
        built = _build_step(task_dir, step)
        if built is not None:
            steps_out.append(built)

    return {"id": task_dir.name, "steps": steps_out}


def _build_episode(ep_dir: Path) -> dict[str, Any]:
    """Build one episode object with fields in show order:
    id, opening_bit, tasks, live_task.

    The intro and outro are series-wide (top-level catalogue fields), not
    per-episode, so they are not resolved here.
    """
    ep: dict[str, Any] = {"id": ep_dir.name}

    opening = ep_dir / "opening-bit.json"
    if not opening.is_file():
        log.error("Episode %s missing opening-bit.json (required)", ep_dir.name)
    ep["opening_bit"] = {"text": _read_text_json(opening) if opening.is_file() else ""}

    tasks_dir = ep_dir / "tasks"
    tasks: list[dict[str, Any]] = []
    if tasks_dir.is_dir():
        for task_dir in sorted(p for p in tasks_dir.iterdir() if p.is_dir()):
            task = _build_task(task_dir)
            if task is not None:
                tasks.append(task)
    ep["tasks"] = tasks

    live = ep_dir / "live-task.json"
    if not live.is_file():
        log.error("Episode %s missing live-task.json (required)", ep_dir.name)
    ep["live_task"] = {"text": _read_text_json(live) if live.is_file() else ""}

    return ep


def _find_series_clip(name: str) -> Path | None:
    """A series-wide clip `series/<name>.<ext>`, by extension precedence."""
    base = MEDIA_ROOT / SERIES_DIR
    for ext in MEDIA_EXTS:
        candidate = base / f"{name}{ext}"
        if candidate.is_file():
            return candidate
    return None


def _build_contestants() -> list[dict[str, str]]:
    path = MEDIA_ROOT / CONTESTANTS_JSON
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("contestants.json unreadable: %s", exc)
        return []
    out = []
    for c in data.get("contestants", []):
        cid, name = c.get("id"), c.get("name")
        if cid and name:
            out.append({"id": cid, "name": name})
    return out


def _build_intros() -> list[dict[str, str]]:
    intros_dir = MEDIA_ROOT / INTROS_DIR
    out = []
    if intros_dir.is_dir():
        for f in sorted(p for p in intros_dir.iterdir() if p.is_file()):
            if f.suffix.lower() in MEDIA_EXTS:
                out.append({"clip": f.stem, "path": _rel(f)})
    return out


def build_catalogue() -> dict[str, Any]:
    """Scan the media tree and return the full catalogue payload."""
    episodes_dir = MEDIA_ROOT / EPISODES_DIR
    episodes: list[dict[str, Any]] = []
    if episodes_dir.is_dir():
        for ep_dir in sorted(p for p in episodes_dir.iterdir() if p.is_dir()):
            episodes.append(_build_episode(ep_dir))

    catalogue: dict[str, Any] = {
        "contestants": _build_contestants(),
        "intros": _build_intros(),
    }
    # Series-wide clips (§6.1): opening intro, closing outro, and the lead-in
    # that precedes each task's first clip. Each is optional; the Controller
    # simply disables the matching action when a clip is absent.
    for field, name in (("intro", "intro"), ("outro", "outro"),
                        ("task_lead_in", "task-lead-in")):
        clip = _find_series_clip(name)
        if clip is not None:
            catalogue[field] = _rel(clip)
    catalogue["episodes"] = episodes
    return catalogue
