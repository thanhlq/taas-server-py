"""Framework-agnostic HTTP route definitions.

Define routes via :class:`Controller` subclasses and ``@get``/``@post``/...
decorators. Adapters in ``http_fastapi``/``http_litestar`` register the
resulting routes with a concrete framework, so callers in ``ews`` and other
business libraries stay framework-free.
"""

from platform_core.http.controller import BaseController
from platform_core.http.decorator import delete, get, patch, post, put, route
from platform_core.http.route import HttpMethod, Route

__all__ = [
    'BaseController',
    'HttpMethod',
    'Route',
    'delete',
    'get',
    'patch',
    'post',
    'put',
    'route',
]
