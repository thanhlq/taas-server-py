from datetime import datetime
from enum import StrEnum
from typing import List, Literal, Optional

from platform_core.serialization import ApiResponse
from platform_core.utils.validation import ValidationError


class ResponseStatus(StrEnum):
    """Standard response status values"""

    SUCCESS = 'success'
    FAIL = 'fail'
    ERROR = 'error'

class PaginatedResponseMeta(ApiResponse):
    """
    Metadata for paginated responses, including pagination details.
    """

    page: int = Field(description='Current page number', ge=1)
    page_size: int = Field(description='Number of items per page', ge=1)
    total: int = Field(description='Total number of items across all pages', ge=0)
    total_pages: int = Field(description='Total number of pages', ge=0)
    request_id: Optional[str] = Field(
        default=None, description='Request correlation ID'
    )
    trace_id: Optional[str] = Field(default=None, description='Distributed tracing ID')
    correlation_id: Optional[str]


    def __post_init__(self):
        """
        page >= 1, page_size >= 1, total >= 0, total_pages >= 0
        """
        # Validate that total_pages is consistent with total and page_size
        expected_total_pages = (self.total + self.page_size - 1) // self.page_size
        if self.total_pages != expected_total_pages:
            raise ValueError(
                f"total_pages must be consistent with total and page_size: expected {expected_total_pages}, got {self.total_pages}"
            )
        if self.page > self.total_pages and self.total_pages > 0:
            raise ValueError(
                f"page number {self.page} exceeds total_pages {self.total_pages}"
            )
        if self.total == 0 and self.total_pages != 0:
            raise ValueError("total_pages must be 0 when total is 0")

class ApiLinks(ApiResponse):
    """Links for pagination and related resources"""

    self: Optional[str] = Field(default=None, description='Current resource URL')
    next: Optional[str] = Field(default=None, description='Next page URL')
    previous: Optional[str] = Field(default=None, description='Previous page URL')
    first: Optional[str] = Field(default=None, description='First page URL')
    last: Optional[str] = Field(default=None, description='Last page URL')

class PaginatedResponse[T](ApiResponse):
    """
    Paginated success response for list endpoints.

    Example:
        ```python
        response = PaginatedResponse(
            data=[{"id": 1}, {"id": 2}],
            meta=ApiResponseMeta(),
            pagination={
                "page": 1,
                "page_size": 10,
                "total": 100,
                "total_pages": 10
            }
        )
        ```
    """

    data: List[T]
    status: Literal[ResponseStatus.SUCCESS, ResponseStatus.FAIL, ResponseStatus.ERROR] = ResponseStatus.SUCCESS
    meta: Optional[PaginatedResponseMeta] = None
    links: Optional[ApiLinks] = None


class ProblemDetails(ApiResponse):
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
                ValidationError(field="email", message="Email is required")
            ]
        )
        ```
    """

    type: str = Field(
        default='about:blank',
        description='URI reference identifying the problem type',
        examples=['https://api.example.com/errors/validation-error'],
    )
    title: str = Field(description='Short, human-readable summary of the problem')
    status: int = Field(description='HTTP status code', ge=100, le=599)
    detail: Optional[str] = Field(
        default=None,
        description='Human-readable explanation specific to this occurrence',
    )
    instance: Optional[str] = Field(
        default=None,
        description='URI reference identifying the specific occurrence',
    )

    # Extension fields (custom additions)
    trace_id: Optional[str] = Field(
        default=None,
        description='Distributed tracing ID for debugging',
    )
    request_id: Optional[str] = Field(
        default=None,
        description='Request correlation ID',
    )
    timestamp: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(UTC),
        description='When the error occurred',
    )
    errors: Optional[List[ValidationError]] = Field(
        default=None,
        description='Detailed validation errors',
    )

    class Config:
        json_schema_extra = {
            'examples': [
                {
                    'type': 'https://api.example.com/errors/validation-error',
                    'title': 'Validation Error',
                    'status': 400,
                    'detail': 'The request contains invalid data',
                    'instance': '/users/create',
                    'trace_id': 'abc-123-def-456',
                    'errors': [
                        {
                            'field': 'email',
                            'message': 'Email is required',
                            'code': 'REQUIRED',
                        }
                    ],
                }
            ]
        }


class Response:
    """
    Base HTTP response class, used as the basis for all other response classes.
    This class actually will wrap fastapi or litestar response, and provide a consistent interface for the rest of the codebase.
     - This will allow us to easily switch between different HTTP frameworks in the future if needed, without having to change the rest of the codebase.
     - And also, this will allow us to have a consistent way of handling responses across different HTTP frameworks.
    """
