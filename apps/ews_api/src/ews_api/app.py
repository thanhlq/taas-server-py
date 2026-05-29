"""
The module is responsible for setting up the FastAPI app, including:
  - middleware - ratelimit with redis backend
  - exception handlers
  - cors
  - routes
"""

from platform_core.cli import cli_print_info
from fastapi.concurrency import asynccontextmanager
import asyncio
from platform_core.config.wss import WebSocketConfig
import socketio
from platform_core.http.base_app import BaseApiApplication, AppConfig

from typing import Any, Optional
from http_fastapi.fastapi_app import create_app
from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse
from .setup_env import setup_environment
from platform_core.config import Settings
from fastapi import FastAPI
from logging import Logger
from ews import ews_conrrollers
from http_fastapi.adapters import create_socketio_asgi_app, include_controller
from platform_core.http._websocket_redis_manager import build_websocket_redis_manager


class EwsApplication(BaseApiApplication[FastAPI]):
    _socketio_app: Optional[socketio.ASGIApp] = None

    def __init__(self, settings: Settings, root_path: str) -> None:
        super().__init__(settings, root_path)
        self.build_application()  # Build the app during initialization to ensure _socketio_app is set if WebSocket is enabled

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

    def build_application(self) -> 'FastAPI':

        @asynccontextmanager
        async def lifespan(application: FastAPI):


            # Validate the manager is what we configured. Blocks startup if not.
            if self.config.websocket_config and self.config.websocket_config.debug:
                from platform_core.http._socketio import verify_socketio_manager

                await verify_socketio_manager(
                    server,  # the AsyncServer instance
                    expect_redis=True,  # only require Redis when we asked for it
                    roundtrip=True,  # set False to skip the pub/sub probe
                    timeout=2.0,
                )

            yield  # Startup complete, now run the app

            cli_print_info('Shutting down application...')

        _fastapi_app: FastAPI = _setup_fastapi_app(
            logger=self.logger, app_config=self.config, lifespan=lifespan
        )
        _controllers = self.get_app_controllers()
        for controller in _controllers:
            include_controller(_fastapi_app, controller)
        if self.is_websocket_enabled():
            websocket_config: WebSocketConfig = self.config.websocket_config  # type: ignore
            self._socketio_app, server = create_socketio_asgi_app(
                _fastapi_app,
                *_controllers,
                client_manager=build_websocket_redis_manager(websocket_config),
            )



        return _fastapi_app

    def get_app_controllers(self) -> list[Any]:
        return ews_conrrollers


def _setup_fastapi_app(logger: Logger, app_config: AppConfig, **kwargs) -> FastAPI:
    app: FastAPI = create_app(app_config, **kwargs)

    @app.exception_handler(exc_class_or_status_code=Exception)
    async def global_exception_handler(request: Any, exc: Exception):
        # Print full traceback to console
        print('Unhandled exception occurred:')
        import traceback

        traceback.print_exc()
        return MsgSpecJSONResponse(
            status_code=500,
            content={'detail': 'Internal Server Error'},
        )

    if app_config.ratelimit_config and app_config.ratelimit_config.enabled:
        from http_fastapi.middewares.slowapi_ratelimit import (
            setup_fastapi_rate_limiting,
        )

        setup_fastapi_rate_limiting(app, app_config.ratelimit_config)
    else:
        logger.warning('Rate limiting is disabled.')

    return app


settings, root_path = setup_environment()
_ews_app = EwsApplication(settings, root_path)

app = (
    _ews_app.get_websocket_app()
    if _ews_app.is_websocket_enabled()
    else _ews_app.get_app()
)

__all__ = ('app',)
