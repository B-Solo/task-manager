"""Controller theme: a dark, Taskmaster-flavoured palette, the app-wide
stylesheet, and registration of the bundled Veteran Typewriter font used for
notes and headings.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("controller.style")

ASSETS_DIR = (Path(__file__).resolve().parent.parent / "assets").resolve()
FONT_VETERAN = ASSETS_DIR / "fonts" / "veteran_typewriter-webfont.ttf"

# Filled in by register_fonts() once a QApplication exists.
NOTES_FONT_FAMILY: str | None = None

RED = "#b5322f"
RED_HI = "#c53c38"

APP_QSS = f"""
QWidget {{ background: #16171b; color: #eaeaea;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; }}
QScrollArea {{ border: 0; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QLabel {{ color: #eaeaea; background: transparent; }}

QPushButton {{
    background: #2a2d34; color: #f2f2f2;
    border: 1px solid #3c4049; border-radius: 10px;
    padding: 10px 18px; font-size: 19px;
}}
QPushButton:hover {{ background: #343842; }}
QPushButton:pressed {{ background: #23262c; }}
QPushButton:disabled {{ color: #6a6d73; background: #1d1f24; border-color: #2a2c31; }}

QPushButton[primary="true"] {{
    background: {RED}; border: 1px solid {RED_HI}; color: white; font-weight: bold;
}}
QPushButton[primary="true"]:hover {{ background: {RED_HI}; }}
QPushButton[danger="true"] {{ background: #4a1e1e; border-color: #6e2a2a; }}
QPushButton[danger="true"]:hover {{ background: #5c2626; }}

QMenu {{ background: #22242a; color: #eaeaea; border: 1px solid #3c4049;
    font-size: 21px; }}
QMenu::item {{ padding: 16px 34px; min-width: 240px; }}
QMenu::item:selected {{ background: {RED}; color: white; }}
"""


def register_fonts() -> str | None:
    """Register the Veteran Typewriter font; returns its family name or None."""
    global NOTES_FONT_FAMILY
    try:
        from PySide6.QtGui import QFontDatabase
    except Exception:
        return None
    if not FONT_VETERAN.exists():
        log.warning("Notes font missing at %s", FONT_VETERAN)
        return None
    font_id = QFontDatabase.addApplicationFont(str(FONT_VETERAN))
    if font_id < 0:
        return None
    families = QFontDatabase.applicationFontFamilies(font_id)
    NOTES_FONT_FAMILY = families[0] if families else None
    return NOTES_FONT_FAMILY
