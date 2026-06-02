"""
This module sets up the FastAPI application with necessary configurations, including:
- Installing a custom OpenAPI schema generator that merges msgspec component schemas.
- Adding exception handlers that translate platform_core exceptions to HTTP responses.
- Adding a global exception handler that logs unhandled exceptions and returns a generic error response.
- Applying needed middleware
"""

import logging
import traceback

from fastapi import FastAPI, Request
from platform_core.exceptions import HTTPException as PlatformHTTPException
from platform_core.http.exceptions import ApplicationClientError, ApplicationError
from platform_core.status_codes import (
    HTTP_400_BAD_REQUEST,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from http_fastapi.fastapi_msgspec.openapi import install_msgspec_openapi
from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse

logger = logging.getLogger(__name__)


def _error_response(
    status_code: int,
    detail: str,
    *,
    error_type: str,
    extra: object | None = None,
) -> MsgSpecJSONResponse:
    payload: dict[str, object] = {'detail': detail, 'error': error_type}
    if extra is not None:
        payload['extra'] = extra
    return MsgSpecJSONResponse(status_code=status_code, content=payload)


def setup_fastapi_app(app: FastAPI, settings: object | None = None) -> FastAPI:
    """Install OpenAPI integration + typed exception handlers on ``app``.

    ``settings`` is accepted for forward compatibility but currently unused.
    """
    install_msgspec_openapi(app)

    @app.exception_handler(PlatformHTTPException)
    async def platform_http_exception_handler( # pyright: ignore[reportUnusedFunction]
        request: Request, exc: PlatformHTTPException
    ) -> MsgSpecJSONResponse:
        """Map platform_core HTTPException (and subclasses) to JSON responses.

        Uses each exception's declared ``status_code`` and ``detail``. Covers
        ``ClientException`` (400), ``NotFoundException`` (404), etc.
        """
        return _error_response(
            status_code=exc.status_code,
            detail=exc.detail,
            error_type=exc.__class__.__name__,
            extra=exc.extra,
        )

    @app.exception_handler(ApplicationClientError)
    async def application_client_error_handler( # pyright: ignore[reportUnusedFunction]
        request: Request, exc: ApplicationClientError
    ) -> MsgSpecJSONResponse:
        """Map ``ApplicationClientError`` (and subclasses, e.g. ``ValidationError``,
        ``PasswordValidationError``, ``AuthorizationError``) to HTTP 400."""

        return _error_response(
            status_code=HTTP_400_BAD_REQUEST,
            detail=exc.detail or str(exc) or 'Bad Request',
            error_type=exc.__class__.__name__,
        )

    @app.exception_handler(ApplicationError)
    async def application_error_handler( # pyright: ignore[reportUnusedFunction]
        request: Request, exc: ApplicationError
    ) -> MsgSpecJSONResponse:
        """Map non-client ``ApplicationError`` to HTTP 500 with traceback logged."""
        logger.exception('ApplicationError at %s', request.url)

        return _error_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.detail or 'Internal Server Error',
            error_type=exc.__class__.__name__,
        )

    @app.exception_handler(Exception)
    async def global_exception_handler( # pyright: ignore[reportUnusedFunction]
        request: Request, exc: Exception
    ) -> MsgSpecJSONResponse:
        # Safety net for anything not handled above. Log full traceback.
        logger.error('Unhandled exception at %s', request.url)
        traceback.print_exc()

        return _error_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Internal Server Error',
            error_type=exc.__class__.__name__,
        )

    return app
