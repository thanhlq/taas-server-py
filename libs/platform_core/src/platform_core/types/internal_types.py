from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from typing_extensions import TypeAlias
    from platform_core.types.asgi_types import ASGIApp, Scope
    from platform_core.handlers.asgi_handlers import ASGIRouteHandler
    from platform_core.handlers.http_handlers import HTTPRouteHandler
    from platform_core.handlers.websocket_handlers import WebsocketRouteHandler


RouteHandlerType: TypeAlias = "HTTPRouteHandler | WebsocketRouteHandler | ASGIRouteHandler"