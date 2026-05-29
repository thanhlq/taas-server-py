"""Socket.IO adapter for Litestar.

Unlike the raw-WebSocket adapter (``_websocket.py``), Socket.IO is its own
ASGI application. The neutral server + handler registration lives in
``platform_core.http._socketio``; here we only mount that server in front of
the Litestar app so both share one ASGI entry point.

The returned object is the ASGI app you hand to uvicorn — Socket.IO traffic on
``socketio_path`` is handled by the server, everything else falls through to
Litestar.
"""
from __future__ import annotations

from typing import Any

import socketio
from litestar import Litestar
from platform_core.http import BaseController, BaseApiApplication
from platform_core.http._socketio import (
    build_socketio_server,
    register_controller,
)


def create_socketio_asgi_app(
    app: Litestar,
    *controllers: BaseController,
    server: socketio.AsyncServer | None = None,
    socketio_path: str = 'socket.io',
    app_context: BaseApiApplication | None = None,
    **server_kwargs: Any,
) -> socketio.ASGIApp:
    """Build (or reuse) a Socket.IO server, register ``controllers`` on it, and
    wrap the Litestar ``app`` so both are served from one ASGI app."""
    server = server or build_socketio_server(**server_kwargs)
    for controller in controllers:
        register_controller(server, controller)
    return socketio.ASGIApp(
        server,
        other_asgi_app=app,
        socketio_path=socketio_path,
    )
