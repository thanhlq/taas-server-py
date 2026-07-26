"""
Containing app configuration for FastAPI.
"""

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from foundation.http import AppConfig

from http_fastapi.fastapi_msgspec.openapi import install_msgspec_openapi
from http_fastapi.middewares.request_context import RequestContextMiddleware


def configure_app(app: FastAPI, config: AppConfig, **kwargs) -> FastAPI:

    # 3. Install MsgSpec OpenAPI support (must be after app creation)
    install_msgspec_openapi(app)

    # Middlewares
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=7)

    # 4. Add a simple root endpoint for testing
    app.add_api_route(
        '/', lambda: {'message': f'Hello from {config.name}!'}, methods=['GET']
    )

    return app
