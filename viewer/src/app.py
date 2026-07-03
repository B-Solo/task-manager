"""Viewer entry point: full-screen Qt window on the TV + WebSocket server.

Run with:  python viewer/src/app.py   (or from viewer/src: python app.py)
"""

from __future__ import annotations

import logging
import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import assets  # noqa: E402
from display.window import ViewerWindow  # noqa: E402
from websocket_server import NetworkBridge, ViewerServer  # noqa: E402

log = logging.getLogger("viewer")


def _target_screen():
    """Prefer the external (HDMI) display; fall back to primary."""
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()
    for screen in screens:
        if screen is not primary:
            return screen
    return primary


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = QApplication(sys.argv)
    # Let a terminal Ctrl+C terminate the process immediately. The network
    # thread is a daemon, so it dies with the main thread.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    font_family = assets.register_fonts()
    if font_family:
        log.info("Registered score font: %s", font_family)
    else:
        log.warning("Veteran Typewriter font not registered; using default")

    window = ViewerWindow(font_family=font_family)

    screen = _target_screen()
    window.setScreen(screen)
    window.setGeometry(screen.geometry())

    bridge = NetworkBridge()
    bridge.commandReceived.connect(window.handle_command)
    window.send_message.connect(bridge.send)

    server = ViewerServer(bridge)
    server.start()

    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
