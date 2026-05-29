"""
FastAPI/Starlette implementation of the framework-neutral
:class:`platform_core.http.WebSocketSession`.

This use socketio instead of native FastAPI WebSockets, so it can be used alongside
"""

from __future__ import annotations
import socketio

from typing import Any

# FIXME
class SocketIOWebSocketSession:
    """Thin wrapper exposing a Starlette ``WebSocket`` as a
    :class:`platform_core.http.WebSocketSession`."""

    _socket: socketio.AsyncServer

    def __init__(self, socket: socketio.AsyncServer) -> None:
        self._socket = socket

    @property
    def raw(self) -> socketio.AsyncServer:
        """The underlying Socket.IO server, for framework-specific needs."""
        return self._socket

    async def accept(self) -> None:


    async def receive_text(self) -> str:
        return await self._socket.receive_text()

    async def receive_json(self) -> Any:
        return await self._socket.receive_json()

    async def send_text(self, data: str) -> None:
        await self._socket.send_text(data)

    async def send_json(self, data: Any) -> None:
        await self._socket.send_json(data)

    async def close(self, code: int = 1000) -> None:
        await self._socket.close(code=code)
