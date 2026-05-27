"""Base controller for framework-agnostic HTTP route declarations.

A :class:`Controller` subclass collects route metadata attached by the
decorators in :mod:`platform_core.http.decorator` and exposes them through
:meth:`get_routes`. Adapters consume those routes to register them with a
concrete HTTP framework (FastAPI, Litestar, ...).
"""

from __future__ import annotations

from typing import ClassVar, Sequence

from platform_core.http.decorator import (
    ROUTE_ATTR,
    SIO_HANDLER_ATTR,
    WS_ROUTE_ATTR,
)
from platform_core.http.route import Route, SocketIOHandler, WebSocketRoute


class BaseController:
    api_prefix: ClassVar[str] = ''
    tags: ClassVar[Sequence[str] | None] = None

    def _collect(self, attr_name: str) -> list:
        """Collect route metadata stored under ``attr_name`` across the MRO.

        Walks the MRO so subclasses inherit parent routes, with subclass
        overrides winning by method name. Each route's handler is rebound to
        this controller instance.
        """
        collected: list = []
        seen: set[str] = set()
        for klass in type(self).__mro__:
            for name, attr in klass.__dict__.items():
                if name in seen:
                    continue
                meta = getattr(attr, attr_name, None)
                if meta is None:
                    continue
                seen.add(name)
                collected.append(meta.with_handler(getattr(self, name)))
        return collected

    def get_routes(self) -> list[Route]:
        """Return HTTP routes with handlers bound to this controller instance."""
        return self._collect(ROUTE_ATTR)

    def get_websocket_routes(self) -> list[WebSocketRoute]:
        """Return WebSocket routes with handlers bound to this instance."""
        return self._collect(WS_ROUTE_ATTR)

    def get_socketio_handlers(self) -> list[SocketIOHandler]:
        """Return Socket.IO event handlers with handlers bound to this instance."""
        return self._collect(SIO_HANDLER_ATTR)
