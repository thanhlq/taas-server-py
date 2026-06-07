from typing import Any

from platform_core.http.context import Context
from platform_core.http.response.responses import PaginatedResponse, ProblemDetails
from platform_core.models.commons import ListResult
from platform_core.utils.validation import ValidationError


def create_paginated_response[T](
    result: ListResult[T], ctx: Context
) -> PaginatedResponse[T]:
    """
    A shortcut to create paginated response from ListResult.

    This function efficiently builds pagination metadata and response in one pass,
    avoiding redundant calculations.
    """

    pass


def create_error_response(
    err: str | Exception | ValidationError | Any | None = None,
    message: str | None = None,
    status: int = 400,
    ctx: Context | None = None,
) -> ProblemDetails:
    """
    A shortcut to create error response with consistent structure.

    This function can be extended to include additional error details, logging, etc.
    """
    pass
