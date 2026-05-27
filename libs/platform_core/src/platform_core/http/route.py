"""Framework-agnostic route metadata.

A :class:`Route` is a plain description of an HTTP endpoint. Adapters in
``http_fastapi``/``http_litestar`` translate it into the equivalent
framework primitive at registration time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from typing_extensions import Literal, TypeAlias

HttpMethod: TypeAlias = Literal[
    "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD",
]


@dataclass
class Route:
    path: str
    methods: tuple[HttpMethod, ...]
    handler: Callable[..., Any]
    name: str | None = None
    summary: str | None = None
    description: str | None = None
    response_model: Any = None
    status_code: int | None = None
    tags: tuple[str, ...] | None = None
    permissions: tuple[str, ...] | None = None
    middleware: tuple[Any, ...] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def with_handler(self, handler: Callable[..., Any]) -> Route:
        """Return a copy of this route with the handler replaced.

        Used when a controller binds an unbound method to its instance.
        """
        return Route(
            path=self.path,
            methods=self.methods,
            handler=handler,
            name=self.name,
            summary=self.summary,
            description=self.description,
            response_model=self.response_model,
            status_code=self.status_code,
            tags=self.tags,
            permissions=self.permissions,
            middleware=self.middleware,
            extra=dict(self.extra),
        )


@dataclass
class WebSocketRoute:
    """Framework-agnostic description of a WebSocket endpoint.

    The handler receives a :class:`platform_core.http.websocket.WebSocketSession`
    that the adapter wraps around its native socket.
    """

    path: str
    handler: Callable[..., Any]
    name: str | None = None
    permissions: tuple[str, ...] | None = None
    middleware: tuple[Any, ...] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def with_handler(self, handler: Callable[..., Any]) -> WebSocketRoute:
        return WebSocketRoute(
            path=self.path,
            handler=handler,
            name=self.name,
            permissions=self.permissions,
            middleware=self.middleware,
            extra=dict(self.extra),
        )


@dataclass
class SocketIOHandler:
    """Framework-agnostic description of a Socket.IO event handler.

    Socket.IO is an event-based protocol (layered over WebSocket / HTTP
    long-polling) rather than a single bidirectional stream. Handlers bind to
    named events (``connect``, ``disconnect``, or custom events like
    ``subscribe``) within a namespace. The adapter wires these onto a
    ``socketio.AsyncServer`` and passes each handler a framework-neutral
    session wrapper.
    """

    event: str
    handler: Callable[..., Any]
    namespace: str = '/'
    name: str | None = None

    def with_handler(self, handler: Callable[..., Any]) -> SocketIOHandler:
        return SocketIOHandler(
            event=self.event,
            handler=handler,
            namespace=self.namespace,
            name=self.name,
        )
