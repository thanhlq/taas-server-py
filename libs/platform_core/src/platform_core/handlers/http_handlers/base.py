# .venv/lib/python3.13/site-packages/litestar/handlers/http_handlers/base.py

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, AnyStr, Mapping, Sequence, TypedDict, cast

from platform_core.types.asgi_types import ASGIApp
from platform_core.types.empty import EmptyType

if TYPE_CHECKING:
    from typing import Any, Awaitable, Callable

class ResponseHandlerMap(TypedDict):
    default_handler: Callable[[Any], Awaitable[ASGIApp]] | EmptyType
    response_type_handler: Callable[[Any], Awaitable[ASGIApp]] | EmptyType