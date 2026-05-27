"""Adapters that bridge framework-agnostic ``platform_core.http`` definitions
into Litestar primitives."""
from http_litestar.adapters._controller import (
    build_handler_for_route,
    build_router_for_controller,
    build_ws_handler_for_route,
    include_controller,
    register_controllers,
)
from http_litestar.adapters._websocket import LitestarWebSocketSession
from http_litestar.adapters._websocket_socketio import create_socketio_asgi_app

__all__ = [
    "LitestarWebSocketSession",
    "build_handler_for_route",
    "build_router_for_controller",
    "build_ws_handler_for_route",
    "create_socketio_asgi_app",
    "include_controller",
    "register_controllers",
]
