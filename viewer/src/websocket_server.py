"""WebSocket server (protocol §2–§6) running on a background asyncio thread,
bridged to the Qt GUI thread with signals.

Envelope-level concerns (JSON validity, size, unknown types) and the
`get_catalogue` request are handled here on the network thread. Display
commands are forwarded to the GUI thread via `commandReceived`; the window
sends any resulting `error` back through `NetworkBridge.send`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading

import websockets
from PySide6.QtCore import QObject, Signal

import catalogue
import protocol

log = logging.getLogger("viewer.ws")


class NetworkBridge(QObject):
    commandReceived = Signal(dict)
    clientConnected = Signal()
    clientDisconnected = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._active_ws = None

    def send(self, message: dict) -> None:
        """Schedule a message to the active client (callable from any thread)."""
        loop, ws = self._loop, self._active_ws
        if loop is None or ws is None:
            log.debug("Dropping message, no active client: %s", message.get("type"))
            return
        text = protocol.dumps(message)
        try:
            asyncio.run_coroutine_threadsafe(ws.send(text), loop)
        except Exception:
            log.exception("Failed to schedule send")


class ViewerServer:
    def __init__(self, bridge: NetworkBridge, host: str = "", port: int = protocol.PORT):
        self._bridge = bridge
        self._host = host
        self._port = port
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ws-server",
                                        daemon=True)
        self._thread.start()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._bridge._loop = loop
        try:
            loop.run_until_complete(self._start_server())
            log.info("Viewer listening on :%d", self._port)
            loop.run_forever()
        except Exception:
            log.exception("WebSocket server crashed")

    async def _start_server(self) -> None:
        # websockets>=13: serve() must be awaited inside a running loop.
        self._server = await websockets.serve(
            self._handler, self._host, self._port, max_size=None
        )

    async def _handler(self, ws) -> None:
        self._bridge._active_ws = ws
        self._bridge.clientConnected.emit()
        peer = getattr(ws, "remote_address", "?")
        log.info("Controller connected: %s", peer)
        try:
            async for raw in ws:
                await self._on_raw(ws, raw)
        except websockets.ConnectionClosed:
            pass
        finally:
            if self._bridge._active_ws is ws:
                self._bridge._active_ws = None
            self._bridge.clientDisconnected.emit()
            log.info("Controller disconnected: %s", peer)

    async def _on_raw(self, ws, raw) -> None:
        if isinstance(raw, (bytes, bytearray)):
            await self._reply(ws, protocol.error_message(
                None, protocol.BAD_REQUEST, "binary frames are not supported"))
            return
        if len(raw.encode("utf-8")) > protocol.MAX_MESSAGE_BYTES:
            await self._reply(ws, protocol.error_message(
                None, protocol.TOO_LARGE, "message exceeds size limit"))
            return
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            await self._reply(ws, protocol.error_message(
                None, protocol.BAD_REQUEST, "invalid JSON"))
            return
        if not isinstance(message, dict):
            await self._reply(ws, protocol.error_message(
                None, protocol.BAD_REQUEST, "message must be a JSON object"))
            return

        mtype = message.get("type")
        ref = message.get("id")

        if mtype == protocol.GET_CATALOGUE:
            await self._send_catalogue(ws)
        elif mtype in protocol.COMMANDS:
            # display command -> GUI thread; it replies via NetworkBridge.send
            self._bridge.commandReceived.emit(message)
        else:
            await self._reply(ws, protocol.error_message(
                ref, protocol.UNKNOWN_TYPE, f"unknown type: {mtype!r}",
                mtype if isinstance(mtype, str) else None))

    async def _send_catalogue(self, ws) -> None:
        try:
            payload = catalogue.build_catalogue()
        except Exception as exc:
            log.exception("Catalogue build failed")
            await self._reply(ws, protocol.error_message(
                None, protocol.INTERNAL, f"catalogue build failed: {exc}",
                protocol.GET_CATALOGUE))
            return
        await self._reply(ws, protocol.catalogue_message(payload))

    @staticmethod
    async def _reply(ws, message: dict) -> None:
        try:
            await ws.send(protocol.dumps(message))
        except Exception:
            log.exception("Failed to send reply")
