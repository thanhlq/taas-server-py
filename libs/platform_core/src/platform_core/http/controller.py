"""
 - The idea is to define a base controller class that can be used to create controllers for different types of routes (HTTP, WebSocket, etc.).
 - And also the key point is to use this controller for definition of HTTP routes, which will allow us to have a consistent way.
 - This base controller will be used to wire up the route handlers (like HTTPRouteHandler, WebsocketRouteHandler, etc.) with the actual
    route handler functions.
 - And then, we can use any http framework (like FastAPI, Flask, etc.) to implement the actual route handlers

Examples:

```python
from platform_core.http.controller import BaseController
from platform_core.http.decorators import get, post, delete, patch, put

class ProjectController(BaseController):

    @get('/projects')
    def list_projects(self, ) -> ASGIApp:

"""

from platform_core.types.asgi_types import ASGIApp, Scope
from platform_core.types.internal_types import RouteHandlerType

class BaseController:

    def __init__(self, route_handler: RouteHandlerType):