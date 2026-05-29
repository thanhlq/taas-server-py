"""Framework-neutral Socket.IO integration.

Socket.IO's ``AsyncServer`` is already independent of the web framework — the
same server is mounted onto FastAPI or Litestar by the per-framework adapters
in ``http_fastapi``/``http_litestar``. This module therefore owns the neutral
pieces: a session wrapper handed to handlers, the server factory, and
controller registration. The framework adapters only mount the resulting ASGI
app.

Business handlers never import ``socketio`` directly; they accept a
:class:`SocketIOSession` and rely on the ``@socketio_event`` decorator.
"""
from __future__ import annotations
from logging import Logger

from typing import Any

import socketio

from platform_core.http.controller import BaseController


class SocketIOSession:
    """Framework-neutral wrapper over a ``socketio.AsyncServer`` + ``sid``.

    Passed to every ``@socketio_event`` handler so business code can emit and
    manage rooms without importing ``socketio`` or any web framework.
    """

    def __init__(
        self,
        server: socketio.AsyncServer,
        sid: str,
        namespace: str = '/',
    ) -> None:
        self._server = server
        self.sid = sid
        self.namespace = namespace

    @property
    def server(self) -> socketio.AsyncServer:
        """The underlying server, for advanced/framework-specific needs."""
        return self._server

    async def emit(
        self,
        event: str,
        data: Any = None,
        *,
        to: str | None = None,
        room: str | None = None,
        skip_sid: str | None = None,
    ) -> None:
        """Emit ``event``. Defaults to broadcasting on this namespace; pass
        ``to``/``room`` to target a specific client or room."""
        await self._server.emit(
            event,
            data,
            to=to,
            room=room,
            skip_sid=skip_sid,
            namespace=self.namespace,
        )

    async def emit_to_caller(self, event: str, data: Any = None) -> None:
        """Emit ``event`` back to the client that triggered this handler."""
        await self._server.emit(
            event, data, to=self.sid, namespace=self.namespace
        )

    async def enter_room(self, room: str) -> None:
        await self._server.enter_room(self.sid, room, namespace=self.namespace)

    async def leave_room(self, room: str) -> None:
        await self._server.leave_room(self.sid, room, namespace=self.namespace)

    async def close(self) -> None:
        await self._server.disconnect(self.sid, namespace=self.namespace)


def build_socketio_server(client_manager=None, logger: Logger | bool = False, **kwargs: Any) -> socketio.AsyncServer:
    """Create an ``AsyncServer`` with sensible defaults for ASGI hosting.

    ``cors_allowed_origins='*'`` is the default so browser Socket.IO clients
    can connect during development; override via ``kwargs`` for production.
    """

    print("Building Socket.IO server with kwargs:", kwargs)

    kwargs.setdefault('async_mode', 'asgi')
    kwargs.setdefault('cors_allowed_origins', '*')
    if client_manager is not None:
        kwargs['client_manager'] = client_manager
    if logger:
        kwargs['logger'] = logger
        kwargs['engineio_logger'] = logger
    return socketio.AsyncServer(**kwargs)


def _make_dispatch(server: socketio.AsyncServer, handler_meta: Any):
    handler = handler_meta.handler
    event = handler_meta.event
    namespace = handler_meta.namespace

    async def dispatch(sid: str, *args: Any) -> Any:
        session = SocketIOSession(server, sid, namespace)
        # ``connect`` is called as (sid, environ, auth); custom events as
        # (sid, data). Hand the business handler the most useful payload.
        if event == 'connect':
            data = args[1] if len(args) >= 2 else None
        else:
            data = args[0] if args else None
        return await handler(session, data)

    return dispatch


def register_controller(
    server: socketio.AsyncServer,
    controller: BaseController,
) -> socketio.AsyncServer:
    """Register all of ``controller``'s Socket.IO handlers on ``server``."""
    for handler_meta in controller.get_socketio_handlers():
        server.on(
            handler_meta.event,
            _make_dispatch(server, handler_meta),
            namespace=handler_meta.namespace,
        )
    return server


def build_server_for_controllers(
    *controllers: BaseController,
    **server_kwargs: Any,
) -> socketio.AsyncServer:
    """Build a server and register one or more controllers on it."""
    server = build_socketio_server(**server_kwargs)
    for controller in controllers:
        register_controller(server, controller)
    return server
