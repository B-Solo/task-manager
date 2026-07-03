"""Controller entry point: operator touch UI + WebSocket client.

Run with:  python controller/src/app.py [--host taskmaster-viewer.local]
The host may be an mDNS name (default) or a raw IP; use --host localhost when
running the Viewer on the same machine for testing.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

import catalogue as cat_mod  # noqa: E402
import protocol  # noqa: E402
import style  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ws_client import ClientBridge, ControllerClient  # noqa: E402

log = logging.getLogger("controller")

DEFAULT_HOST = "taskmaster-viewer.local"


def main() -> int:
    parser = argparse.ArgumentParser(description="Taskmaster Controller")
    parser.add_argument("--host", default=os.environ.get("TM_VIEWER_HOST", DEFAULT_HOST),
                        help="Viewer hostname or IP (default: %(default)s)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = QApplication(sys.argv)
    # Let a terminal Ctrl+C terminate the process immediately. The client
    # thread is a daemon, so it dies with the main thread.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    style.register_fonts()
    app.setStyleSheet(style.APP_QSS)
    _seal = style.ASSETS_DIR / "seal.png"
    if _seal.exists():
        from PySide6.QtGui import QIcon  # noqa: PLC0415
        app.setWindowIcon(QIcon(str(_seal)))

    bridge = ClientBridge()
    client = ControllerClient(bridge, host=args.host)
    window = MainWindow(client, protocol.IdSequencer())

    bridge.connected.connect(lambda: window.set_connected(True))
    bridge.disconnected.connect(lambda: window.set_connected(False))
    bridge.catalogueReceived.connect(window.on_catalogue)
    bridge.errorReceived.connect(window.on_error)

    cached = cat_mod.load_cached()
    if cached is not None:
        window._init_from_catalogue(cached)
        log.info("Loaded cached catalogue (%d episodes)",
                 len(cached.episode_ids()))
    window.render()

    client.start()
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
