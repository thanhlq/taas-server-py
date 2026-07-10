from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from typing_extensions import TypeAlias
    from foundation.handlers.asgi_handlers import ASGIRouteHandler
    from foundation.handlers.http_handlers import HTTPRouteHandler
    from foundation.handlers.websocket_handlers import WebsocketRouteHandler


RouteHandlerType: TypeAlias = "HTTPRouteHandler | WebsocketRouteHandler | ASGIRouteHandler"
