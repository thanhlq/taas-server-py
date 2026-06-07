"""
High performance models for API responses based on ApiResponse (msgspec.Struct).

Following the design principles of:
- RFC 7807/9457 Problem Details for HTTP APIs (https://datatracker.ietf.org/doc/html/rfc7807)
"""
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Optional

import msgspec
from platform_core.serialization import ApiResponse


class ResponseStatus(StrEnum):
    """Standard response status values"""

    SUCCESS = 'success'
    FAIL = 'fail'
    ERROR = 'error'


class ValidationErrorDetail(ApiResponse):
    """A single field-level validation error (RFC 7807 ``errors`` extension).

    ``platform_core.utils.validation.ValidationError`` is an *exception* type, so
    it cannot live inside a serialized response body. This struct is the
    serializable counterpart used to describe individual validation failures.
    """

    message: str
    field: Optional[str] = None
    code: Optional[str] = None


class PaginatedResponseMeta(ApiResponse):
    """
    Metadata for paginated responses, including pagination details.
    """

    page: Annotated[int, msgspec.Meta(ge=1, description='Current page number')]
    page_size: Annotated[
        int, msgspec.Meta(ge=1, description='Number of items per page')
    ]
    total: Annotated[
        int, msgspec.Meta(ge=0, description='Total number of items across all pages')
    ]
    total_pages: Annotated[int, msgspec.Meta(ge=0, description='Total number of pages')]
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    correlation_id: Optional[str] = None

    def __post_init__(self) -> None:
        """
        page >= 1, page_size >= 1, total >= 0, total_pages >= 0
        """
        # Validate that total_pages is consistent with total and page_size
        expected_total_pages = (self.total + self.page_size - 1) // self.page_size
        if self.total_pages != expected_total_pages:
            raise ValueError(
                f'total_pages must be consistent with total and page_size: '
                f'expected {expected_total_pages}, got {self.total_pages}'
            )
        if self.page > self.total_pages and self.total_pages > 0:
            raise ValueError(
                f'page number {self.page} exceeds total_pages {self.total_pages}'
            )
        if self.total == 0 and self.total_pages != 0:
            raise ValueError('total_pages must be 0 when total is 0')


class ApiLinks(ApiResponse):
    """Links for pagination and related resources"""

    # ``self`` would collide with the generated ``__init__(self, ...)`` parameter,
    # so the attribute is ``self_`` while the serialized key stays ``self``.
    self_: Optional[str] = msgspec.field(name='self', default=None)
    next: Optional[str] = None
    previous: Optional[str] = None
    first: Optional[str] = None
    last: Optional[str] = None


class PaginatedResponse[T](ApiResponse):
    """
    Paginated success response for list endpoints.

    Example:
        ```python
        response = PaginatedResponse(
            data=[{"id": 1}, {"id": 2}],
            meta=PaginatedResponseMeta(
                page=1,
                page_size=10,
                total=100,
                total_pages=10,
            ),
        )
        ```
    """

    data: list[T]
    status: ResponseStatus = ResponseStatus.SUCCESS
    meta: Optional[PaginatedResponseMeta] = None
    links: Optional[ApiLinks] = None


class ErrorResponse(ApiResponse):
    """
    RFC 7807/9457 Problem Details for HTTP APIs.
    Standard format for error responses.

    RESTful APIs:
        - Content-Type: application/problem+json
        - Body: JSON object with fields like "type", "title", "status", "detail", etc.
        - Status code: Matches the "status" field in the body (e.g. 400, 404, 500)

    Example:
        ```python
        problem = ProblemDetails(
            type="https://api.example.com/errors/validation-error",
            title="Validation Error",
            status=400,
            detail="The 'email' field is required",
            instance="/users/create",
            trace_id="abc-123",
            errors=[
                ValidationErrorDetail(field="email", message="Email is required")
            ],
        )
        ```
    """

    title: Annotated[
        str, msgspec.Meta(description='Short, human-readable summary of the problem')
    ]
    status: Annotated[int, msgspec.Meta(ge=100, le=599, description='HTTP status code')]
    type: Annotated[
        str,
        msgspec.Meta(
            description='URI reference identifying the problem type',
            examples=['https://api.example.com/errors/validation-error'],
        ),
    ] = 'about:blank'
    detail: Optional[str] = None
    instance: Optional[str] = None

    # Extension fields (custom additions)
    trace_id: Optional[str] = None
    request_id: Optional[str] = None
    timestamp: datetime = msgspec.field(default_factory=lambda: datetime.now(UTC))
    errors: Optional[list[ValidationErrorDetail]] = None


class Response:
    """
    Base HTTP response class, used as the basis for all other response classes.
    This class actually will wrap fastapi or litestar response, and provide a consistent interface for the rest of the codebase.
     - This will allow us to easily switch between different HTTP frameworks in the future if needed, without having to change the rest of the codebase.
     - And also, this will allow us to have a consistent way of handling responses across different HTTP frameworks.
    """
