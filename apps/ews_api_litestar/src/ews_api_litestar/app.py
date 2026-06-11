"""
The module is responsible for setting up the Litestar app, including:
  - exception handlers
  - cors / compression
  - routes (framework-agnostic ``ews`` controllers)
  - websocket (Socket.IO) wiring
  - cache service registration

The route definitions live in ``ews`` and are framework-agnostic; this module
wires them into a Litestar app via ``http_litestar.adapters``. It mirrors
``ews_api.app`` so the two framework variants stay consistent.
"""
from contextlib import asynccontextmanager
from typing import Any, Optional

import socketio
from ews import conrrollers as ews_conrrollers
from http_litestar.adapters import (
    build_router_for_controller,
    create_socketio_asgi_app,
)
from http_litestar.create_app import build_app
from http_litestar.middewares.request_context import RequestContextMiddleware
from iam import iam_controllers
from litestar import Litestar
from litestar.response import Response
from litestar.status_codes import HTTP_500_INTERNAL_SERVER_ERROR
from platform_core.cli import cli_print_info
from platform_core.config import Settings
from platform_core.config.wss import WebSocketConfig
from platform_core.facade.cache import ICacheService
from platform_core.http._websocket_redis_manager import build_websocket_redis_manager
from platform_core.http.base_app import BaseApiApplication
from platform_core.state.service_registry import register_service
from store_redis import RedisStore, create_redis_client

from .bootstrap import root_path, settings


class EwsLitestarApplication(BaseApiApplication[Litestar]):
    """Litestar variant of the ews_api application."""

    _socketio_app: Optional[socketio.ASGIApp] = None
    _socketio_server: Optional[socketio.AsyncServer] = None

    def __init__(self, settings: Settings, root_path: str) -> None:
        super().__init__(settings, root_path)
        # Build the app during initialization so ``_socketio_app`` is set when
        # WebSocket is enabled.
        self.build_application()

    def get_app_id(self) -> str:
        return 'ews_api_litestar'

    def is_websocket_enabled(self) -> bool:
        return True

    def get_websocket_app(self) -> socketio.ASGIApp:
        if self._socketio_app is None:
            raise RuntimeError(
                'WebSocket app has not been built yet. Call get_app() first to build the app.'
            )
        return self._socketio_app

    def build_application(self) -> Litestar:
        controllers = self.get_app_controllers()

        @asynccontextmanager
        async def lifespan(_app: Litestar):
            cli_print_info('Starting up the application...')

            # Register the cache backend so the ``@cache`` decorator on the
            # controllers can resolve ``ICacheService`` at request time.
            _cache_config = settings.app.get_cache_config()
            _redis_client = create_redis_client(_cache_config.get_redis_config())
            register_service(ICacheService, RedisStore(_redis_client))

            if self.config.websocket_config and self.config.websocket_config.debug:
                cli_print_info('🐛 WebSocket debug mode is enabled.')

            yield  # Startup complete, now run the app

            cli_print_info('Shutting down the application...')

        # Litestar invokes exception handlers synchronously, so this must be a
        # plain (non-async) function. Scope it to 500 only so Litestar keeps
        # handling normal HTTP errors (404, 422, ...) itself.
        def _internal_error_handler(_request: Any, exc: Exception) -> Response:
            import traceback

            traceback.print_exception(type(exc), exc, exc.__traceback__)
            return Response(
                content={'detail': 'Internal Server Error'},
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            )

        litestar_app: Litestar = build_app(
            route_handlers=[build_router_for_controller(c) for c in controllers],
            lifespan=[lifespan],
            exception_handlers={HTTP_500_INTERNAL_SERVER_ERROR: _internal_error_handler},
            middleware=[RequestContextMiddleware],
        )

        # Per-route rate limiting (parity with the FastAPI adapter). The
        # framework-agnostic ``@get(..., ratelimit=...)`` declarations are
        # enforced by a guard that reads this shared limiter from app state.
        ratelimit_config = self.config.ratelimit_config
        if ratelimit_config and ratelimit_config.enabled:
            from http_litestar.middewares.slowapi_ratelimit import (
                setup_litestar_rate_limiting,
            )

            setup_litestar_rate_limiting(litestar_app, ratelimit_config)
        else:
            cli_print_info('Rate limiting is disabled.')

        if self.is_websocket_enabled():
            websocket_config: WebSocketConfig = self.config.websocket_config  # type: ignore[assignment]
            self._socketio_app, self._socketio_server = create_socketio_asgi_app(
                litestar_app,
                *controllers,
                client_manager=build_websocket_redis_manager(websocket_config),
            )

        return litestar_app

    def get_app_controllers(self) -> list[Any]:
        return [*iam_controllers, *ews_conrrollers]


_ews_app = EwsLitestarApplication(settings, root_path)

app = (
    _ews_app.get_websocket_app()
    if _ews_app.is_websocket_enabled()
    else _ews_app.get_app()
)

__all__ = ('app',)
