"""Base controller for framework-agnostic HTTP route declarations.

A :class:`Controller` subclass collects route metadata attached by the
decorators in :mod:`platform_core.http.decorator` and exposes them through
:meth:`get_routes`. Adapters consume those routes to register them with a
concrete HTTP framework (FastAPI, Litestar, ...).
"""

from __future__ import annotations

from typing import ClassVar, Sequence

from platform_core.http.decorator import ROUTE_ATTR
from platform_core.http.route import Route


class BaseController:
    api_prefix: ClassVar[str] = ''
    tags: ClassVar[Sequence[str] | None] = None

    def get_routes(self) -> list[Route]:
        """Return routes with each handler bound to this controller instance."""
        routes: list[Route] = []
        seen: set[str] = set()
        # Walk the MRO so subclasses inherit parent routes, with subclass
        # overrides winning by name.
        for klass in type(self).__mro__:
            for name, attr in klass.__dict__.items():
                if name in seen:
                    continue
                meta: Route | None = getattr(attr, ROUTE_ATTR, None)
                if meta is None:
                    continue
                seen.add(name)
                bound_handler = getattr(self, name)
                routes.append(meta.with_handler(bound_handler))
        return routes
