"""Framework-agnostic HTTP route definitions.

Define routes via :class:`BaseController` subclasses and ``@get``/``@post``/...
decorators (``@websocket`` for raw WebSocket endpoints, ``@socketio_event``
for Socket.IO event handlers). Adapters in ``http_fastapi``/``http_litestar``
register the resulting routes with a concrete framework, so callers in ``ews``
and other business libraries stay framework-free.
"""

from __future__ import annotations

from platform_core.http._websocket import WebSocketSession
from platform_core.http.base_app import AppConfig, BaseApiApplication
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

from . import status
from .cache import cache

from ._socketio import verify_socketio_manager

__all__ = [
    'BaseController',
    'BaseApiApplication',
    'AppConfig',
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
    'cache',
    'status',
    'verify_socketio_manager',
]
