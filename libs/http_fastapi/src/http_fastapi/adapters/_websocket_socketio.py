"""Socket.IO adapter for FastAPI.

Unlike the raw-WebSocket adapter (``_websocket.py``), Socket.IO is its own
ASGI application. The neutral server + handler registration lives in
``platform_core.http._socketio``; here we only mount that server in front of
the FastAPI app so both share one ASGI entry point.

The returned object is the ASGI app you hand to uvicorn — Socket.IO traffic on
``socketio_path`` is handled by the server, everything else falls through to
FastAPI.
"""
from __future__ import annotations
from logging import Logger

from typing import Any

import socketio
from fastapi import FastAPI
from platform_core.http import BaseController
from platform_core.http._socketio import (
    build_socketio_server,
    register_controller,
)


def create_socketio_asgi_app(
    app: FastAPI,
    *controllers: BaseController,
    server: socketio.AsyncServer | None = None,
    socketio_path: str = 'socket.io',
    client_manager: socketio.AsyncManager | None = None,
    **server_kwargs: Any,
) -> tuple[socketio.ASGIApp, socketio.AsyncServer]:
    """
    Build (or reuse) a Socket.IO server, register ``controllers`` on it, and
    wrap the FastAPI ``app`` so both are served from one ASGI app.
    """

    # how to setup redis pubsub for this socketio server? if we want to run multiple instances, we need to share state between them. the socketio docs recommend using a message queue like redis for this: https://python-socketio.readthedocs.io/en/latest/redis.html#redis-manager
    logger: Logger | bool = server_kwargs.pop('logger', False)

    server = server or build_socketio_server(client_manager=client_manager, logger=logger, **server_kwargs)
    for controller in controllers:
        register_controller(server, controller)

    _socketio_app: socketio.ASGIApp = socketio.ASGIApp(
        server,
        other_asgi_app=app,
        socketio_path=socketio_path,
    )

    return _socketio_app, server
