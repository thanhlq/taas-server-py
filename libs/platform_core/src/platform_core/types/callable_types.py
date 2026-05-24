from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Generator,
    TypeVar,
)

if TYPE_CHECKING:
    from typing_extensions import TypeAlias

    from platform_core.app import TaasApp
    from platform_core.config.app import AppConfig
    from platform_core.handlers.base import BaseRouteHandler
    from platform_core.types.asgi_types import ASGIApp, Message, Method, Scope
    from platform_core.types.helper_types import SyncOrAsyncUnion
    from platform_core.types.protocols import Logger


from platform_core.middleware.base import DefineMiddleware
from platform_core.types.asgi_types import ASGIApp, Scope

if TYPE_CHECKING:
    from typing_extensions import TypeAlias


AsyncAnyCallable: TypeAlias = Callable[..., Awaitable[Any]]
AnyCallable: TypeAlias = Callable[..., Any]
AnyGenerator: TypeAlias = 'Generator[Any, Any, Any] | AsyncGenerator[Any, Any]'
ExceptionLoggingHandler: TypeAlias = 'Callable[[Logger, Scope, list[str]], None]'
GetLogger: TypeAlias = 'Callable[..., Logger]'
LifespanHook: TypeAlias = (
    'Callable[[Litestar], SyncOrAsyncUnion[Any]] | Callable[[], SyncOrAsyncUnion[Any]]'
)
