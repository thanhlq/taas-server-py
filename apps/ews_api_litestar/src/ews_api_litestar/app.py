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
from db.check_db import a_check_db_consistency
from ews import get_ews_controllers
from foundation.cli import cli_print_info
from foundation.config import Settings
from foundation.config.wss import WebSocketConfig
from foundation.factory import FoundationFactory
from foundation.http._websocket_redis_manager import build_websocket_redis_manager
from foundation.app.base_app import BaseApiApplication
from foundation.messaging.factory import MessagingFactory
from foundation.utils.icons import Icons
from http_litestar.adapters import (
    build_router_for_controller,
    create_socketio_asgi_app,
)
from http_litestar.create_app import build_app
from http_litestar.middewares.request_context import RequestContextMiddleware
from iam import get_iam_controllers
from iam.iam_factory import IamFactory
from iam_keycloak import IamServiceFactory
from litestar import Litestar
from litestar.response import Response
from litestar.status_codes import HTTP_500_INTERNAL_SERVER_ERROR
from messaging_faststream import initialize_messaging_service, messaging
from resiliant import ResiliantServiceFactory
from store_redis import RedisCacheServiceFactory

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
        controllers = self._get_enabled_app_controllers()

        @asynccontextmanager
        async def lifespan(_app: Litestar):
            cli_print_info('Starting up the application...')

            await self._init_services()

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

    def _init_cache_service(self) -> None:
        """Register the shared Redis cache service (mirrors ``ews_api``)."""
        cache_config = settings.app.get_cache_config()
        if cache_config.enabled:
            RedisCacheServiceFactory.create(cache_config)
            self.logger.info(f'{Icons.REDIS} Redis cache service initialised')
        else:
            self.logger.info(
                f'{Icons.REDIS} {Icons.OFF} Cache disabled by configuration'
            )

    async def _init_database_service(self) -> None:
        if settings.app.check_database_consistency():
            cli_print_info('Checking database consistency...')
            if len(await a_check_db_consistency()) > 0:
                raise RuntimeError(
                    'Database consistency check failed. Please check the logs for details.'
                )

    async def _init_services(self) -> None:
        """Composition root: register every backend service the request
        handlers resolve from the service registry.

        Kept in lock-step with ``ews_api.app.EwsApplication._init_services`` so
        the FastAPI and Litestar variants expose identical runtime behaviour.
        """
        await self._init_database_service()

        FoundationFactory.init_default_services()
        self._init_cache_service()
        FoundationFactory.use_resiliant(ResiliantServiceFactory())
        MessagingFactory.init_factory(
            messaging_service=await initialize_messaging_service(),
            decorator=messaging,
        )
        IamFactory.initialize_iam(IamServiceFactory())

    def _get_enabled_app_controllers(self) -> list[Any]:
        return [*get_iam_controllers(), *get_ews_controllers()]


_ews_app = EwsLitestarApplication(settings, root_path)

app = (
    _ews_app.get_websocket_app()
    if _ews_app.is_websocket_enabled()
    else _ews_app.get_app()
)

__all__ = ('app',)
