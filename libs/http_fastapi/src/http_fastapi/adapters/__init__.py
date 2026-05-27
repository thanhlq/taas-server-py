"""Adapters that bridge framework-agnostic ``platform_core.http`` definitions
into FastAPI primitives."""
from http_fastapi.adapters._controller import (
    build_router_for_controller,
    include_controller,
)
from http_fastapi.adapters._websocket import FastAPIWebSocketSession
from http_fastapi.adapters._websocket_socketio import create_socketio_asgi_app

__all__ = [
    "FastAPIWebSocketSession",
    "build_router_for_controller",
    "create_socketio_asgi_app",
    "include_controller",
]
