from dataclasses import dataclass
from typing import Optional

# 2x faster than urllib.parse.parse_qs and supports nested structures (e.g. items[]=1&items[]=2 -> {'items': ['1', '2']})
from fast_query_parsers import parse_url_encoded_dict
from starlette.requests import Request
from starlette.responses import Response

from platform_core.models.auth import AuthUser


@dataclass
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
    res: Response | None = None
    auth_info: Optional[AuthorizationInfo] = None
    query: dict[str, str | int] | None = None

    def pack(self):
        # Ensure that auth_info is always initialized to an instance of AuthorizationInfo
        if self.auth_info is None:
            self.auth_info = AuthorizationInfo()

        # Parse query parameters from the request and store them in the context
        # Note: In both Fastapi and Litestar
        # print(f"Parsing query parameters from request: {self.req.scope['query_string']}")
        qs = self.req.scope['query_string']
        if qs:
            self.query = parse_url_encoded_dict(qs, True)

            # print debug all values
            print('\nParsed query parameters:')
            print('==========================================')

            items = self.query.items()

            print(f'Total query parameters: {len(items)}')

            # print(f"items: {self.query.get('items')}")

            for k, v in items:
                if type(v) in (str, int):
                    print(f'\t {k}={v} (type={type(v)})')
                elif isinstance(v, list):
                    # print line by line if it's a list
                    print(f'\t {k.replace("[]", "")}=[...] (type={type(v)})')
                    for item in v:
                        print(f'\t\t- {item} (type={type(item)})')
                else:
                    print(f'\t: {k}={v} (type={type(v)})')
            print('==========================================\n')
