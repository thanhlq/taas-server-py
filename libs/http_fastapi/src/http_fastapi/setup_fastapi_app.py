"""
This module sets up the FastAPI application with necessary configurations, including:
- Installing a custom OpenAPI schema generator that merges msgspec component schemas.
- Adding a global exception handler that logs unhandled exceptions and returns a generic error response.
- Applying needed middleware
"""
from platform_core.config import AppSettings
from fastapi.responses import JSONResponse
from fastapi import FastAPI, Request

from http_fastapi.base_fastapi_app import build_app
from http_fastapi.fastapi_msgspec.openapi import install_msgspec_openapi


def setup_fastapi_app(app: FastAPI, settings: AppSettings) -> FastAPI:
    install_msgspec_openapi(app)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # Print full traceback to console
        print(f'Unhandled exception occurred with {request.url}:')
        import traceback

        traceback.print_exc()

        return JSONResponse(
            status_code=500,
            content={'detail': 'Internal Server Error'},
        )

    return app
