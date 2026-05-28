"""
The module is responsible for setting up the FastAPI app, including:
  - middleware - ratelimit with redis backend
  - exception handlers
  - cors
  - routes
"""

from typing import Any
from http_fastapi.base_fastapi_app import build_app
from http_fastapi.fastapi_msgspec.openapi import install_msgspec_openapi
from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse
from .setup_env import setup_environment
from platform_core.config import AppSettings, Settings
from fastapi import FastAPI
from logging import getLogger
from store_redis import RedisStore


def is_rate_limit_enabled(settings: Settings) -> bool:
    return bool(settings.server.RATE_LIMIT_ENABLED)


def _setup_fastapi_app() -> FastAPI:
    settings = setup_environment()

    logger = getLogger()

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

    if is_rate_limit_enabled(settings):
        from http_fastapi.middewares.slowapi_ratelimit import (
            setup_fastapi_rate_limiting,
        )

        setup_fastapi_rate_limiting(app, settings)
    else:
        logger.warning('Rate limiting is disabled.')

    return app


app = _setup_fastapi_app()
