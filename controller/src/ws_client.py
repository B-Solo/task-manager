"""WebSocket client (protocol §4) on a background asyncio thread, bridged to
the Qt GUI thread with signals.

Connects to the Viewer by hostname/IP, reconnects automatically with backoff,
and forwards `catalogue`/`error` messages to the GUI. Commands are sent
fire-and-forget from the GUI thread via `send`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading

import websockets
from PySide6.QtCore import QObject, Signal

import protocol

log = logging.getLogger("controller.ws")

INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 10.0


class ClientBridge(QObject):
    connected = Signal()
    disconnected = Signal()
    catalogueReceived = Signal(dict)
    errorReceived = Signal(dict)


class ControllerClient:
    def __init__(self, bridge: ClientBridge, host: str,
                 port: int = protocol.PORT) -> None:
        self.bridge = bridge
        self._host = host
        self._port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._stop = False
        self._was_connected = False
        self._thread: threading.Thread | None = None

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ws-client",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop = True
        loop, ws = self._loop, self._ws
        if loop and ws:
            asyncio.run_coroutine_threadsafe(ws.close(), loop)

    def set_host(self, host: str) -> None:
        """Point at a new host and force a reconnect."""
        self._host = host
        loop, ws = self._loop, self._ws
        if loop and ws:
            asyncio.run_coroutine_threadsafe(ws.close(), loop)

    @property
    def host(self) -> str:
        return self._host

    # -- sending ----------------------------------------------------------
    def send(self, message: dict) -> bool:
        """Fire-and-forget send from the GUI thread. Returns False if offline."""
        loop, ws = self._loop, self._ws
        if loop is None or ws is None:
            return False
        try:
            asyncio.run_coroutine_threadsafe(ws.send(protocol.dumps(message)), loop)
            return True
        except Exception:
            log.exception("Send failed")
            return False

    # -- background loop --------------------------------------------------
    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        loop.run_until_complete(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        backoff = INITIAL_BACKOFF
        while not self._stop:
            url = f"ws://{self._host}:{self._port}"
            try:
                async with websockets.connect(url, max_size=None) as ws:
                    self._ws = ws
                    self._was_connected = True
                    backoff = INITIAL_BACKOFF
                    log.info("Connected to %s", url)
                    self.bridge.connected.emit()
                    async for raw in ws:
                        self._on_message(raw)
            except Exception as exc:
                log.debug("Connect to %s failed: %s", url, exc)
            finally:
                self._ws = None
                if self._was_connected:
                    self.bridge.disconnected.emit()
                    self._was_connected = False
            if self._stop:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

    def _on_message(self, raw) -> None:
        if isinstance(raw, (bytes, bytearray)):
            return
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Ignoring non-JSON message from Viewer")
            return
        mtype = message.get("type")
        if mtype == protocol.CATALOGUE:
            self.bridge.catalogueReceived.emit(message.get("payload", {}))
        elif mtype == protocol.ERROR:
            self.bridge.errorReceived.emit(message.get("payload", {}))
        else:
            log.debug("Ignoring unexpected message type %r", mtype)
