from http import HTTPStatus
from math import ceil
from typing import Any

from platform_core.http.context import Context
from platform_core.http.response.responses import (
    ErrorResponse,
    PaginatedResponse,
    PaginatedResponseMeta,
    ResponseStatus,
    ValidationErrorDetail,
)
from platform_core.models.commons import ListResult
from platform_core.utils.validation import ValidationError

_DEFAULT_PAGE = 1
_DEFAULT_PAGE_SIZE = 20


def _request_correlation(
    ctx: Context | None,
) -> tuple[str | None, str | None, str | None]:
    """Best-effort ``(request_id, trace_id, correlation_id)`` from request headers."""
    req = getattr(ctx, 'req', None)
    headers = getattr(req, 'headers', None)
    if not headers:
        return None, None, None
    return (
        headers.get('x-request-id'),
        headers.get('x-trace-id') or headers.get('traceparent'),
        headers.get('x-correlation-id'),
    )


def _pagination_params(ctx: Context | None, fallback_size: int) -> tuple[int, int]:
    """Resolve ``(page, page_size)`` from the request query params, with fallbacks."""
    page = _DEFAULT_PAGE
    page_size = fallback_size or _DEFAULT_PAGE_SIZE
    req = getattr(ctx, 'req', None)
    params = getattr(req, 'query_params', None)
    if params:
        try:
            page = max(1, int(params.get('page', page)))
        except (TypeError, ValueError):
            pass
        try:
            page_size = max(1, int(params.get('page_size', page_size)))
        except (TypeError, ValueError):
            pass
    return page, page_size


def create_paginated_response[T](
    result: ListResult[T] | list[T], ctx: Context | None = None
) -> PaginatedResponse[T]:
    """
    A shortcut to create paginated response from ListResult.

    This function efficiently builds pagination metadata and response in one pass,
    avoiding redundant calculations.
    """
    if isinstance(result, list):
        total = len(result)
        data = result
    else:
        total = result.total_count
        data = result.data

    page, page_size = _pagination_params(
        ctx, fallback_size=len(data) or _DEFAULT_PAGE_SIZE
    )
    total_pages = ceil(total / page_size) if page_size else 0
    request_id, trace_id, correlation_id = _request_correlation(ctx)

    meta = PaginatedResponseMeta(
        # Clamp ``page`` to a valid range so PaginatedResponseMeta validation passes.
        page=min(page, total_pages) if total_pages else page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        request_id=request_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
    )
    return PaginatedResponse(
        data=data, status=ResponseStatus.SUCCESS, meta=meta
    )


def create_success_response[T](data: T, ctx: Context | None = None) -> T:
    """
    A shortcut to create success response with consistent structure.

    This function can be extended to include additional metadata, logging, etc.
    """
    return data


def _status_title(status: int) -> str:
    """Return the standard HTTP reason phrase for ``status`` (fallback ``'Error'``)."""
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return 'Error'


def create_error_response(
    err: str | Exception | ValidationError | Any | None = None,
    message: str | None = None,
    status: int = 400,
    ctx: Context | None = None,
) -> ErrorResponse:
    """
    A shortcut to create error response with consistent structure.

    This function can be extended to include additional error details, logging, etc.
    """
    title = _status_title(status)
    detail = message
    errors: list[ValidationErrorDetail] | None = None

    if isinstance(err, ValidationError):
        title = 'Validation Error'
        detail = detail or str(err)
        errors = [ValidationErrorDetail(message=str(err))]
    elif isinstance(err, Exception):
        detail = detail or (str(err) or type(err).__name__)
    elif isinstance(err, str):
        detail = detail or err

    request_id, trace_id, _ = _request_correlation(ctx)
    instance = None
    req = getattr(ctx, 'req', None)
    url = getattr(req, 'url', None)
    if url is not None:
        instance = getattr(url, 'path', None)

    return ErrorResponse(
        title=title,
        status=status,
        detail=detail,
        instance=instance,
        trace_id=trace_id,
        request_id=request_id,
        errors=errors,
    )

