from datetime import datetime
from typing import Optional, List
from platform_core.serialization import ApiResponse
from platform_core.utils.validation import ValidationError


class ProblemDetails(ApiResponse):
    """
    RFC 7807/9457 Problem Details for HTTP APIs.
    Standard format for error responses.

    Content-Type: application/problem+json

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
