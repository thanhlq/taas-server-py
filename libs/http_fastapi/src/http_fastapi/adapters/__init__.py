"""Adapters that bridge framework-agnostic ``platform_core.http`` definitions
into FastAPI primitives."""
from http_fastapi.adapters._controller import (
    build_router_for_controller,
    include_controller,
)

__all__ = [
    "build_router_for_controller",
    "include_controller",
]
