"""Framework-agnostic HTTP route definitions.

Define routes via :class:`BaseController` subclasses and ``@get``/``@post``/...
decorators (``@websocket`` for raw WebSocket endpoints, ``@socketio_event``
for Socket.IO event handlers). Adapters in ``http_fastapi``/``http_litestar``
register the resulting routes with a concrete framework, so callers in ``ews``
and other business libraries stay framework-free.
"""

from platform_core.http.controller import BaseController
from platform_core.http.decorator import (
    delete,
    get,
    patch,
    post,
    put,
    route,
    socketio_event,
    websocket,
)
from platform_core.http.route import (
    HttpMethod,
    Route,
    SocketIOHandler,
    WebSocketRoute,
)
from platform_core.http._websocket import WebSocketSession

__all__ = [
    'BaseController',
    'HttpMethod',
    'Route',
    'SocketIOHandler',
    'WebSocketRoute',
    'WebSocketSession',
    'delete',
    'get',
    'patch',
    'post',
    'put',
    'route',
    'socketio_event',
    'websocket',
]
