"""
The module is responsible for setting up the FastAPI app, including:
  - middleware - ratelimit with redis backend
  - exception handlers
  - cors
  - routes

IMPORTANT:
- This app can be started directly with uvicorn, or it can be imported and used as a module in another FastAPI app.
"""

from logging import Logger
from typing import TYPE_CHECKING, Any

from db.check_db import a_check_db_consistency
from ews import get_ews_controllers
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from foundation.cli import cli_print_info
from foundation.config import Settings
from foundation.config.wss import WebSocketConfig
from foundation.factory import FoundationFactory
from foundation.http._websocket_redis_manager import build_websocket_redis_manager
from foundation.app.base_app import AppConfig, BaseApiApplication
from foundation.messaging.factory import MessagingFactory
from foundation.utils.icons import Icons
from http_fastapi import create_app
from http_fastapi.adapters import create_socketio_asgi_app, include_controller
from http_fastapi.setup_fastapi_app import setup_fastapi_app
from iam import get_iam_controllers
from iam.iam_factory import IamFactory
from iam_keycloak import IamServiceFactory

# from messaging_kafka import initialize_messaging_service
from messaging_faststream import initialize_messaging_service, messaging
from resiliant import ResiliantServiceFactory
from store_redis import RedisCacheServiceFactory

from .bootstrap import root_path, settings

if TYPE_CHECKING:
    from foundation.observability.types import InstrumentSettings


class EwsApplication(BaseApiApplication[FastAPI]):
    def __init__(
        self,
        *,
        settings: Settings,
        runtime_path: str,
    ) -> None:
        super().__init__(settings, runtime_path, None)

        self.build_application()  # Build the app during initialization to ensure _socketio_app is set if WebSocket is enabled

    def instrument_settings(self) -> 'InstrumentSettings':
        from foundation.observability.types import InstrumentSettings

        if not hasattr(self, '_instrument_settings'):
            self._instrument_settings = InstrumentSettings()
        return self._instrument_settings

    def get_app_id(self) -> str:
        return 'ews_api'

    def build_application(self) -> 'FastAPI':

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await self._init_services()
            yield  # Startup complete, now run the app
            cli_print_info('Shutting down application...')

        _fastapi_app: FastAPI = _setup_fastapi_app(
            logger=self.logger, app_config=self.config, lifespan=lifespan
        )

        _controllers = self._get_enabled_app_controllers()
        for controller in _controllers:
                include_controller(_fastapi_app, controller)

        if self.is_websocket_enabled():
            websocket_config: WebSocketConfig = self.config.websocket_config  # type: ignore
            self._socketio_app, server = create_socketio_asgi_app(
                _fastapi_app,
                *_controllers,
                client_manager=build_websocket_redis_manager(websocket_config),
                logging_enabled=self.is_wss_logging_enable(),
            )

        return _fastapi_app

    def _init_cache_service(self) -> None:
        """Register the shared Redis cache service (mirrors the API lifespan)."""
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

    def _init_api_routes(self, app: FastAPI) -> None:
        """Add API routes to the FastAPI app."""
        for controller in self._get_enabled_app_controllers():
            include_controller(app, controller)


def _setup_fastapi_app(logger: Logger, app_config: AppConfig, **kwargs) -> FastAPI:
    app: FastAPI = create_app(app_config, **kwargs)

    # Register typed exception handlers (ApplicationClientError -> 400,
    # ApplicationError -> 500, plus a catch-all 500). Registered first so
    # FastAPI's dispatcher picks the most specific class for any exception.
    setup_fastapi_app(app, app_config)

    if app_config.ratelimit_config and app_config.ratelimit_config.enabled:
        from http_fastapi.middewares.slowapi_ratelimit import (
            setup_fastapi_rate_limiting,
        )

        setup_fastapi_rate_limiting(app, app_config.ratelimit_config)
    else:
        logger.warning('Rate limiting is disabled.')

    return app


_ews_app = EwsApplication(settings=settings, runtime_path=root_path)

app = _ews_app.websocket_app if _ews_app.is_websocket_enabled() else _ews_app.get_app()

__all__ = ('app',)
