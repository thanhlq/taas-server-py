"""
FastAPI/Starlette implementation of the framework-neutral
:class:`platform_core.http.WebSocketSession`.

By using natively supported WebSockets, this adapter allows you to leverage FastAPI's
full feature set (e.g. dependency injection) in your WebSocket endpoints, while still
adhering to the framework-neutral :class:`platform_core.http.WebSocketSession` interface.
"""

from __future__ import annotations

from typing import Any

from starlette.websockets import WebSocket


class FastAPIWebSocketSession:
    """Thin wrapper exposing a Starlette ``WebSocket`` as a
    :class:`platform_core.http.WebSocketSession`."""

    def __init__(self, socket: WebSocket) -> None:
        self._socket = socket

    @property
    def raw(self) -> WebSocket:
        """The underlying Starlette socket, for framework-specific needs."""
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
