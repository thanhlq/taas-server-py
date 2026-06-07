from typing import Optional

from starlette.requests import Request
from starlette.responses import Response

from platform_core.models.auth import AuthUser


class AuthorizationInfo:
    """Authorization information extracted from the request, such as user details and authz URL."""

    authz_url: Optional[str] = None


class Context:
    """
    Context object for storing request-specific data during the lifecycle of an HTTP request.

    This can be used to store data that needs to be accessed across different layers of the application
    (e.g. controllers, services, repositories) without having to pass it explicitly through function
    parameters.

    Example usage:
        ```python
        from platform_core.http.context import Context

        def my_controller(context: Context):
            # Store some data in the context
            context.user_id = get_user_id_from_request()
            # Call a service that also accepts the context
            return my_service(context)

        def my_service(context: Context):
            # Access the user_id stored in the context by the controller
            user_id = context.user_id
            # Perform some business logic with the user_id
            ...
        ```
    """

    user_id: str = 'anonymous'
    user: AuthUser | None = None
    req: Request
    res: Response
    auth_info: Optional[AuthorizationInfo] = None
