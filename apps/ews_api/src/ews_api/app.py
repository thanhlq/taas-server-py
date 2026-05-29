"""
The module is responsible for setting up the FastAPI app, including:
  - middleware - ratelimit with redis backend
  - exception handlers
  - cors
  - routes
"""
import socketio
from ews_api_litestar.main import _controller

from platform_core.http.base_app import BaseApiApplication, AppConfig

from typing import Any, Optional
from http_fastapi.base_fastapi_app import build_app
from http_fastapi.fastapi_msgspec.openapi import install_msgspec_openapi
from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse
from .setup_env import setup_environment
from platform_core.config import Settings
from fastapi import FastAPI
from logging import Logger
from ews import ews_conrrollers
from http_fastapi.adapters import create_socketio_asgi_app, include_controller

class EwsApplication(BaseApiApplication[FastAPI]):
    _socketio_app: Optional[socketio.ASGIApp] = None

    def __init__(self, settings: Settings, root_path: str) -> None:
        super().__init__(settings, root_path)

    def get_app_id(self) -> str:
        return 'ews_api'

    def get_websocket_app(self) -> socketio.ASGIApp:
        if self._socketio_app is None:
            raise RuntimeError('WebSocket app has not been built yet. Call get_app() first to build the app.')
        return self._socketio_app

    def is_websocket_enabled(self) -> bool:
        return True

    def build_application(self) -> 'FastAPI':
        _fastapi_app: FastAPI = _setup_fastapi_app(logger=self.logger, app_config=self.config)
        _controllers = self.get_app_controllers()
        for controller in _controllers:
            include_controller(_fastapi_app, controller)

        if self.is_websocket_enabled():
            # Socket.IO is the default real-time transport: it wraps the FastAPI app so
            # Socket.IO traffic (default path /socket.io) and HTTP share one ASGI app.
            # The raw-WebSocket route registered by include_controller still works too.
            self._socketio_app = create_socketio_asgi_app(_fastapi_app, *_controllers)

        return _fastapi_app

    def get_app_controllers(self) -> list[Any]:
        return ews_conrrollers


def _setup_fastapi_app(logger: Logger, app_config: AppConfig) -> FastAPI:
    app_config.default_response_class = MsgSpecJSONResponse
    app: FastAPI = build_app(app_config)
    install_msgspec_openapi(app)

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
_ews_app.build_application()

app = _ews_app.get_websocket_app() if _ews_app.is_websocket_enabled() else _ews_app.get_app()

__all__ = ('app',)
