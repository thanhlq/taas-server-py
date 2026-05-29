"""
The module is responsible for setting up the FastAPI app, including:
  - middleware - ratelimit with redis backend
  - exception handlers
  - cors
  - routes
"""
from platform_core.cli import show_api_app_info

from platform_core.http.base_app import BaseApiApplication, AppConfig

from typing import Any
from http_fastapi.base_fastapi_app import build_app
from http_fastapi.fastapi_msgspec.openapi import install_msgspec_openapi
from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse
from .setup_env import setup_environment
from platform_core.config import AppSettings, Settings
from fastapi import FastAPI
from logging import getLogger, Logger
from store_redis import RedisStore


class EwsApplication(BaseApiApplication[FastAPI]):
    def __init__(self, settings: Settings, root_path: str) -> None:
        super().__init__(settings, root_path)

    def get_app_id(self) -> str:
        return 'ews_api'

    def build_app(self) -> FastAPI:
        return _setup_fastapi_app(logger=self.logger, app_config=self.config)


def _setup_fastapi_app(logger: Logger, app_config: AppConfig) -> FastAPI:
    app: FastAPI = build_app(default_response_class=MsgSpecJSONResponse)
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
_ews_app.show_app_info()

app = _ews_app.get_app()

__all__ = ('app',)
