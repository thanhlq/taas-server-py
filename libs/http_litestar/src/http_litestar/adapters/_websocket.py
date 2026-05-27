"""Litestar implementation of the framework-neutral
:class:`platform_core.http.WebSocketSession`."""
from __future__ import annotations

from typing import Any

from litestar import WebSocket


class LitestarWebSocketSession:
    """Thin wrapper exposing a Litestar ``WebSocket`` as a
    :class:`platform_core.http.WebSocketSession`."""

    def __init__(self, socket: WebSocket) -> None:
        self._socket = socket

    @property
    def raw(self) -> WebSocket:
        """The underlying Litestar socket, for framework-specific needs."""
        return self._socket

    async def accept(self) -> None:
        await self._socket.accept()

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
