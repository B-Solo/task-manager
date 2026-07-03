"""Filesystem helpers for the Viewer: the media root, safe path resolution,
well-known asset locations, and font registration.
"""

from __future__ import annotations

from pathlib import Path

# viewer/src/assets.py -> viewer/media
MEDIA_ROOT = (Path(__file__).resolve().parent.parent / "media").resolve()

# Well-known assets (relative to MEDIA_ROOT)
DEFAULT_BACKGROUND = "assets/backgrounds/default.png"
SEAL_RED = "assets/seal.png"
SEAL_GOLD = "assets/seal-gold.png"
SCOREBOARD_FRAME = "assets/scoreboard/frame.png"
SCOREBOARD_BACKGROUND = "assets/scoreboard/background.jpg"
FONT_VETERAN = "assets/fonts/veteran_typewriter/veteran_typewriter-webfont.ttf"
CONTESTANTS_JSON = "contestants.json"
INTROS_DIR = "assets/intros"
EPISODES_DIR = "episodes"

# Extensions the Viewer recognises, in resolution-precedence order.
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
MEDIA_EXTS = VIDEO_EXTS + IMAGE_EXTS


class PathEscapeError(ValueError):
    """Raised when a requested path escapes the media root."""


def resolve_media(rel_path: str) -> Path:
    """Resolve *rel_path* (relative to the media root) to an absolute path,
    rejecting anything that escapes the root or is absolute.

    Raises PathEscapeError on traversal/absolute paths (protocol §5.2).
    Does not check existence — the caller decides what a missing file means.
    """
    if rel_path is None:
        raise PathEscapeError("empty path")
    candidate = Path(rel_path)
    if candidate.is_absolute():
        raise PathEscapeError(f"absolute path not allowed: {rel_path}")
    resolved = (MEDIA_ROOT / candidate).resolve()
    # Python 3.9+: is_relative_to
    if not resolved.is_relative_to(MEDIA_ROOT):
        raise PathEscapeError(f"path escapes media root: {rel_path}")
    return resolved


def is_video(path: Path | str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS


def is_image(path: Path | str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


def asset_abs(rel_path: str) -> Path:
    """Absolute path to a known asset under the media root (trusted input)."""
    return (MEDIA_ROOT / rel_path).resolve()


def register_fonts() -> str | None:
    """Register bundled fonts with Qt. Returns the Veteran Typewriter family
    name if it loaded, else None. Safe to call after QApplication exists.
    """
    try:
        from PySide6.QtGui import QFontDatabase
    except Exception:
        return None
    font_path = asset_abs(FONT_VETERAN)
    if not font_path.exists():
        return None
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id < 0:
        return None
    families = QFontDatabase.applicationFontFamilies(font_id)
    return families[0] if families else None
