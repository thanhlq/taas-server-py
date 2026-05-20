from typing import Callable

from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response

from rest_fastapi.fastapi_msgspec.requests import MSGSpecJSONRequest


class MsgSpecRoute(APIRoute):
    """APIRoute that decodes JSON request bodies with msgspec.

    Inherits ``APIRoute.__init__`` verbatim so it stays forward-compatible
    with any new FastAPI keyword arguments (e.g. ``strict_content_type``).

    Response-side encoding is handled by setting
    ``default_response_class=MsgSpecJSONResponse`` on the app or router,
    not by this class.
    """

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            request = MSGSpecJSONRequest(request.scope, request.receive)
            return await original_route_handler(request)

        return custom_route_handler