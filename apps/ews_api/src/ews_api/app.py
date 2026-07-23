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
from typing import TYPE_CHECKING, Any, Optional

import socketio
from db.check_db import a_check_db_consistency
from ews import get_ews_controllers
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from foundation.cli import cli_print_info
from foundation.config import Settings
from foundation.config.wss import WebSocketConfig
from foundation.factory import FoundationFactory
from foundation.http._websocket_redis_manager import build_websocket_redis_manager
from foundation.http.base_app import AppConfig, BaseApiApplication
from foundation.messaging.factory import MessagingFactory
from foundation.messaging.types import IMessagingService
from http_fastapi import create_app
from http_fastapi.adapters import create_socketio_asgi_app, include_controller
from http_fastapi.setup_fastapi_app import setup_fastapi_app
from iam import get_iam_controllers
from iam.iam_factory import IamFactory
from iam_keycloak import IamServiceFactory

# from messaging_kafka import initialize_messaging_service
from messaging_faststream import initialize_messaging_service
from resiliant import ResiliantServiceFactory
from store_redis import RedisCacheServiceFactory

from .bootstrap import root_path, settings

if TYPE_CHECKING:
    from foundation.observability.types import InstrumentSettings


class EwsApplication(BaseApiApplication[FastAPI]):
    _socketio_app: Optional[socketio.ASGIApp] = None

    def __init__(
        self,
        *,
        settings: Settings,
        runtime_path: str,
    ) -> None:
        super().__init__(settings, runtime_path, None)

        self._init_services()  # Initialize services before building the app
        self.build_application()  # Build the app during initialization to ensure _socketio_app is set if WebSocket is enabled

    def instrument_settings(self) -> 'InstrumentSettings':
        from foundation.observability.types import InstrumentSettings

        if not hasattr(self, '_instrument_settings'):
            self._instrument_settings = InstrumentSettings()
        return self._instrument_settings

    def get_app_id(self) -> str:
        return 'ews_api'

    def get_websocket_app(self) -> socketio.ASGIApp:
        if self._socketio_app is None:
            raise RuntimeError(
                'WebSocket app has not been built yet. Call get_app() first to build the app.'
            )
        return self._socketio_app

    def is_websocket_enabled(self) -> bool:
        return True

    def enable_ws_logging(self) -> bool:
        return (
            self.config.websocket_config is not None
            and self.config.websocket_config.debug
        )

    def build_application(self) -> 'FastAPI':

        @asynccontextmanager
        async def lifespan(application: FastAPI):

            RedisCacheServiceFactory.create(settings.app.get_cache_config())

            # 01. Check db consistency
            if settings.app.check_database_consistency():
                cli_print_info('Checking database consistency...')
                if len(await a_check_db_consistency()) > 0:
                    raise RuntimeError(
                        'Database consistency check failed. Please check the logs for details.'
                    )

            _controllers = self.get_app_controllers()
            for controller in _controllers:
                include_controller(_fastapi_app, controller)

            # Validate the manager is what we configured. Blocks startup if not.
            if self.config.websocket_config and self.config.websocket_config.debug:
                pass

                # await verify_socketio_manager(
                #     server,  # the AsyncServer instance
                #     expect_redis=True,  # only require Redis when we asked for it
                #     roundtrip=True,  # set False to skip the pub/sub probe
                #     timeout=2.0,
                # )

            _ms: IMessagingService = await initialize_messaging_service(settings)
            MessagingFactory.init_factory(messaging_service=_ms, decorator=None)

            # FIXME: TO BE MIGRATED
            from iam.auth.handlers.init_handlers import (
                register_iam_schema_registry_schemas,
            )
            register_iam_schema_registry_schemas(_ms)

            yield  # Startup complete, now run the app

            cli_print_info('Shutting down application...')

        _fastapi_app: FastAPI = _setup_fastapi_app(
            logger=self.logger, app_config=self.config, lifespan=lifespan
        )

        _controllers = self.get_app_controllers()
        if self.is_websocket_enabled():
            websocket_config: WebSocketConfig = self.config.websocket_config  # type: ignore
            self._socketio_app, server = create_socketio_asgi_app(
                _fastapi_app,
                *_controllers,
                client_manager=build_websocket_redis_manager(websocket_config),
                logging_enabled=self.enable_ws_logging(),
            )

        return _fastapi_app

    def _init_services(self) -> None:
        # Initialize the ResiliantServiceFactory and register it with the FoundationFactory
        FoundationFactory.init_default_services()
        FoundationFactory.use_resiliant(ResiliantServiceFactory())

        IamFactory.set_iam_service_factory(IamServiceFactory())

    def get_app_controllers(self) -> list[Any]:
        return [*get_iam_controllers(), *get_ews_controllers()]


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

app = (
    _ews_app.get_websocket_app()
    if _ews_app.is_websocket_enabled()
    else _ews_app.get_app()
)

__all__ = ('app',)
