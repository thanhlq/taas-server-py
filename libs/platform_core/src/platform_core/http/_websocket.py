"""Framework-agnostic WebSocket session contract.

WebSocket handlers in business libraries (``ews`` etc.) should never import
FastAPI or Litestar types. Instead they accept a :class:`WebSocketSession`,
and the framework adapter wraps its native socket in a concrete
implementation of this protocol before invoking the handler.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WebSocketSession(Protocol):
    """Minimal, framework-neutral view of a WebSocket connection.

    The method set is intentionally the intersection of what FastAPI
    (Starlette) and Litestar sockets expose, so adapters can implement it as a
    thin passthrough.
    """

    async def accept(self) -> None:
        """Accept the incoming connection handshake."""
        ...

    async def receive_text(self) -> str:
        """Receive a single text frame."""
        ...

    async def receive_json(self) -> Any:
        """Receive and decode a single JSON frame."""
        ...

    async def send_text(self, data: str) -> None:
        """Send a text frame."""
        ...

    async def send_json(self, data: Any) -> None:
        """Encode ``data`` as JSON and send it."""
        ...

    async def close(self, code: int = 1000) -> None:
        """Close the connection with the given close ``code``."""
        ...
