"""Adapters that bridge framework-agnostic ``platform_core.http`` definitions
into Litestar primitives."""
from http_litestar.adapters._controller import (
    build_handler_for_route,
    build_router_for_controller,
    include_controller,
    register_controllers,
)

__all__ = [
    "build_handler_for_route",
    "build_router_for_controller",
    "include_controller",
    "register_controllers",
]
